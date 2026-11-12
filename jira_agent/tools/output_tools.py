"""Diagramme und Datei-Exporte. Ergebnisse liegen nur im Speicher des Nutzers und laufen ab.

Die Daten holt das Tool selbst (SELECT bzw. JQL) – das Modell kann keine Zahlen erfinden.
Rückgabe enthält "markdown" (Bild bzw. Download-Link), das der Agent unverändert ausgibt.
"""
from __future__ import annotations

import csv
import io
import re
import math
import threading
from typing import Literal

from jira_agent import CFG
from jira_agent.data import check_readonly_sql
from jira_agent.tools import ToolContext, tool
from jira_agent.tools.jira_tools import EXPORT_MAX_RESULTS, search_issues

_EXPORT_ROWS = int(CFG["data"]["export_row_limit"])
_MAX_POINTS = 50
_CHART_LOCK = threading.RLock()
_NAME_RE = re.compile(r"[^A-Za-z0-9_\-]+")


def _safe_name(name: str, ext: str) -> str:
    base = _NAME_RE.sub("_", name or "").strip("_")[:60] or "export"
    return f"{base}.{ext}"


def _num(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _sql_result(ctx: ToolContext, sql: str) -> dict:
    if ctx.sql is None:
        raise RuntimeError("Keine Tabellen freigegeben – bitte über das Zahnrad unter Datenquellen auswählen.")
    return ctx.sql.query(check_readonly_sql(sql, ctx.selected_tables), row_limit=_EXPORT_ROWS)


@tool(needs=["sql", "files"])
def create_chart(ctx: ToolContext, sql: str, chart_type: Literal["bar", "line", "pie", "scatter"], x: str, y: str,
                 title: str = "") -> dict:
    """Erstellt ein Diagramm (PNG) aus genau einem lesenden SELECT auf freigegebenen Tabellen.
    Das SELECT sollte bereits aggregiert sein (z. B. GROUP BY), max. 50 Punkte.

    sql: SELECT auf freigegebenen Tabellen
    chart_type: Diagrammtyp
    x: Spalte für Kategorien bzw. X-Achse
    y: Spalte mit Zahlenwerten
    title: Überschrift
    """
    res = _sql_result(ctx, sql)
    if "error" in res:
        return res
    return chart_from_result(ctx.files,res,chart_type,x,y,title)


def chart_from_result(files, res: dict, chart_type: str, x: str, y: str, title: str = "") -> dict:
    """Shared renderer; Matplotlib is serialized and every figure is closed on failure."""
    cols = res["columns"]
    if x not in cols or y not in cols:
        raise ValueError(f"Spalten {x!r}/{y!r} nicht im Ergebnis. Vorhanden: {cols}")
    xi, yi = cols.index(x), cols.index(y)
    points = [(row[xi], _num(row[yi])) for row in res["rows"] if _num(row[yi]) is not None]
    ignored = len(res["rows"])-len(points)
    if not points:
        raise ValueError(f"Spalte {y!r} enthält keine endlichen Zahlen.")
    cut = len(points) > _MAX_POINTS
    points = points[:_MAX_POINTS]
    labels, values = [str(p[0]) for p in points], [p[1] for p in points]
    with _CHART_LOCK:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
        try:
            if chart_type == "bar": ax.bar(labels,values)
            elif chart_type == "line": ax.plot(labels,values,marker="o")
            elif chart_type == "scatter":
                xs = [_num(p[0]) for p in points]
                if any(v is None for v in xs):
                    raise ValueError(f"Für scatter muss {x!r} numerisch sein.")
                ax.scatter(xs,values)
            elif chart_type == "pie":
                if any(v < 0 for v in values) or sum(values) <= 0:
                    raise ValueError("Tortendiagramme benötigen nichtnegative Werte und eine positive Summe.")
                ax.pie(values,labels=labels,autopct="%1.0f%%")
            else: raise ValueError("chart_type muss bar, line, pie oder scatter sein.")
            ax.set_title(title or f"{y} nach {x}")
            if chart_type != "pie":
                ax.set_xlabel(x); ax.set_ylabel(y)
                if chart_type in ("bar","line"):
                    plt.setp(ax.get_xticklabels(),rotation=45,ha="right")
            fig.tight_layout()
            buf=io.BytesIO(); fig.savefig(buf,format="png")
        finally:
            plt.close(fig)
    url=files.put(_safe_name(title or "diagramm","png"),"image/png",buf.getvalue())
    return {"markdown":f"![{title or 'Diagramm'}]({url})","punkte":len(points),
            "gekuerzt":cut or bool(res.get("truncated")),"ausgelassene_werte":ignored}


@tool(needs=["files"])
def export_file(ctx: ToolContext, source: Literal["sql", "jql"], query: str, format: Literal["csv", "xlsx"],
                filename: str = "") -> dict:
    """Exportiert Daten als Datei (CSV oder Excel) zum Download. source='sql': ein lesendes SELECT
    auf freigegebenen Tabellen; source='jql': Jira-Tickets per JQL (max. 100).

    source: Datenquelle
    query: SELECT bzw. JQL
    format: Dateiformat
    filename: Dateiname ohne Endung
    """
    if source == "sql":
        res = _sql_result(ctx, query)
        if "error" in res:
            return res
        columns, rows = res["columns"], res["rows"]
    elif source == "jql":
        if ctx.jira is None:
            raise RuntimeError("Kein Jira-Token – bitte über das Zahnrad verbinden.")
        res = search_issues(ctx.jira, query, EXPORT_MAX_RESULTS)
        columns = ["key", "summary", "status", "priority", "components", "assignee", "updated"]
        rows = [[", ".join(i[c]) if isinstance(i.get(c), list) else i.get(c) for c in columns]
                for i in res["issues"]]
    else:
        raise ValueError("source muss sql oder jql sein.")

    return export_result(ctx.files,columns,rows,format,filename or f"export_{source}")


def export_result(files, columns: list, rows: list, format: str, filename: str) -> dict:
    """Create download files from actual results, shared by warehouse/Jira/upload tools."""
    if format == "csv":
        text = io.StringIO()
        writer = csv.writer(text, delimiter=";")   # Semikolon: öffnet sich in deutschem Excel korrekt
        def csv_value(value):
            if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):
                return "'"+value
            return value
        writer.writerow([csv_value(v) for v in columns])
        writer.writerows([csv_value(v) for v in row] for row in rows)
        data, mime = text.getvalue().encode("utf-8-sig"), "text/csv"
    elif format == "xlsx":
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell

        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Data")
        def cells(row):
            result=[]
            for value in row:
                cell=WriteOnlyCell(ws,value="" if value is None else value)
                if isinstance(value,str): cell.data_type="s"
                result.append(cell)
            return result
        ws.append(cells(columns))
        for row in rows:
            ws.append(cells(row))
        buf = io.BytesIO()
        wb.save(buf)
        data = buf.getvalue()
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        raise ValueError("format muss csv oder xlsx sein.")

    name = _safe_name(filename, format)
    url = files.put(name, mime, data)
    return {"markdown": f"[{name} herunterladen]({url})", "zeilen": len(rows),
            "hint": "Textzellen bleiben Text; CSV-Formelpräfixe werden mit einem Apostroph entschärft."}

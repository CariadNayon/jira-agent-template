"""Hochgeladene Dateien lesen (Büroklammer, Strg+V oder Drag & Drop im Chat).

Lesbar: CSV/TSV, Excel (xlsx), Text (txt, md, json, xml, yaml, log) und Text aus PDFs.
Dateien liegen nur im Speicher des Nutzers und laufen nach session.files_ttl_minutes ab.
"""
from __future__ import annotations

import csv
import io
from pathlib import PurePath

from jira_agent.tools import ToolContext, tool
from jira_agent.uploads import image_info

_MAX_TEXT = 20000
_TEXT_TYPES = {".txt", ".md", ".json", ".xml", ".yaml", ".yml", ".log", ".html", ".sql", ".py"}


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_table_text(text: str, max_rows: int) -> dict:
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        return {"columns": [], "rows": [], "row_count": 0}
    return {"columns": rows[0], "rows": rows[1:max_rows + 1], "row_count": len(rows) - 1,
            "gekuerzt": len(rows) - 1 > max_rows}


def read_excel(data: bytes, max_rows: int) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheets = {}
    for ws in wb.worksheets[:10]:
        rows = []
        total = 0
        for row in ws.iter_rows(values_only=True):
            total += 1
            if len(rows) <= max_rows:
                rows.append(["" if v is None else v for v in row])
        sheets[ws.title] = {"columns": rows[0] if rows else [], "rows": rows[1:], "row_count": max(total - 1, 0),
                            "gekuerzt": total - 1 > max_rows}
    wb.close()
    return {"blaetter": sheets}


def read_pdf(data: bytes, start_page: int = 1, max_pages: int = 10, text_offset: int = 0) -> dict:
    from jira_agent.pdf_data import read_pdf as read_pages
    return read_pages(data,start_page,max_pages,text_offset)


@tool(needs=["uploads"])
def list_uploaded_files(ctx: ToolContext) -> dict:
    """Listet die Dateien, die der Nutzer in diesem Chat hochgeladen hat (Name, ID, Größe)."""
    return {"dateien": ctx.uploads.list()}


@tool(needs=["uploads"])
def read_uploaded_file(ctx: ToolContext, file_id: str, max_rows: int = 200, start_page: int = 1, max_pages: int = 10, text_offset: int = 0) -> dict:
    """Liest Tabellen (CSV, Excel), Text und PDF-Text. Für PNG/JPEG/WebP werden nur Metadaten geliefert;
    die referenzierten Bilder stehen dem Modell direkt in der Benutzernachricht zur Verfügung.

    file_id: ID der Datei (siehe list_uploaded_files)
    max_rows: maximale Vorschau-Zeilen je Tabelle (höchstens 1000); für Berechnungen analyze_uploaded_table nutzen
    start_page: erste PDF-Seite, beginnend bei 1
    max_pages: PDF-Seiten je Aufruf, maximal 20; mit next_page weiterblättern
    text_offset: Textposition innerhalb der Startseite; next_text_offset aus vorherigem Ergebnis nutzen
    """
    f = ctx.uploads.get(file_id)
    if f is None:
        raise ValueError("Datei nicht gefunden oder abgelaufen – bitte erneut hochladen.")
    max_rows = max(1, min(int(max_rows), 1000))
    ext = PurePath(f.name).suffix.lower()
    out: dict = {"name": f.name}
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        out.update({"type": "image", **image_info(f.name, f.data)})
    elif ext in (".csv", ".tsv"):
        out.update(read_table_text(_decode(f.data), max_rows))
    elif ext in (".xlsx", ".xlsm"):
        out.update(read_excel(f.data, max_rows))
    elif ext == ".pdf":
        out.update(read_pdf(f.data,start_page,max_pages,text_offset))
    elif ext in _TEXT_TYPES or f.mime.startswith("text/"):
        text = _decode(f.data)
        out.update({"text": text[:_MAX_TEXT], "gekuerzt": len(text) > _MAX_TEXT})
    else:
        raise ValueError(f"Dateityp {ext or f.mime} kann ich nicht lesen. Möglich: CSV, Excel, PDF, Text.")
    return out

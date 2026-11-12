"""Computed upload analysis: structured operations, no user/model code execution."""
from __future__ import annotations

from typing import Literal

from jira_agent.table_data import analyze, load_table
from jira_agent.tools import ToolContext, tool
from jira_agent.tools.output_tools import chart_from_result, export_result


def _table(ctx, file_id, sheet, number_format):
    file = ctx.uploads.get(file_id)
    if file is None:
        raise ValueError('Datei fehlt oder ist in diesem Chat nicht verfügbar. Bitte erneut anhängen.')
    return load_table(file,sheet,number_format)


@tool(needs=['uploads'])
def analyze_uploaded_table(ctx: ToolContext, file_id: str, operation: Literal['profile','rows','aggregate']='profile',
                           sheet: str='', number_format: Literal['auto','de','en']='auto',
                           group_by: list[str] | None=None, aggregations: list[dict] | None=None,
                           filters: list[dict] | None=None, sort_by: str='', sort_desc: bool=False,
                           max_rows: int=100, columns: list[str] | None=None,
                           column_offset: int=0, max_columns: int=25) -> dict:
    """Berechnet Auswertungen über ALLE Zeilen einer hochgeladenen CSV-/Excel-Tabelle, nicht nur die Vorschau.
    Zuerst profile oder read_uploaded_file für Spalten/Blätter nutzen. Bei unklarem Zahlenformat nachfragen.

    file_id: Datei-ID aus den Anhängen dieses Chats
    operation: profile für Typen/Statistik, rows für gefilterte Zeilen, aggregate für Gruppenberechnungen
    Bei Aggregationen zählt size alle Zeilen, count nur nichtleere Werte der angegebenen Spalte.
    sheet: Excel-Blattname; bei mehreren Blättern erforderlich
    number_format: auto nur eindeutige Ganzzahlen; de für 1.234,50; en für 1,234.50
    group_by: Spalten zum Gruppieren, z. B. ["Status"]
    aggregations: Objekte mit column, op (sum/mean/median/min/max/count/size/nunique) und eindeutigem name
    filters: Objekte mit column, op (eq/ne/gt/gte/lt/lte/contains/in/is_empty/not_empty) und value
    sort_by: Spalte im Ergebnis zum Sortieren
    sort_desc: absteigend sortieren
    max_rows: Ergebnisvorschau, maximal 1000; Berechnungen berücksichtigen alle Eingabezeilen
    columns: optional ausgewählte Ergebnis-/Profilspalten, sonst alle
    column_offset: Startposition im Spaltenprofil; mit next_column_offset weiterblättern
    max_columns: Profilspalten pro Aufruf, maximal 50
    """
    return analyze(_table(ctx,file_id,sheet,number_format),operation,group_by,aggregations,filters,sort_by,sort_desc,max_rows,
                   columns,column_offset,max_columns)


@tool(needs=['uploads','files'])
def create_uploaded_chart(ctx: ToolContext, file_id: str, x: str, y: str,
                          chart_type: Literal['bar','line','pie','scatter']='bar', title: str='',
                          sheet: str='', number_format: Literal['auto','de','en']='auto',
                          group_by: list[str] | None=None, aggregations: list[dict] | None=None,
                          filters: list[dict] | None=None, sort_by: str='', sort_desc: bool=False) -> dict:
    """Erstellt ein Diagramm aus einer hochgeladenen Tabelle; Daten werden im Code berechnet.

    file_id: Datei-ID
    x: Ergebnisspalte für X-Achse/Kategorien
    y: numerische Ergebnisspalte für Y-Achse
    chart_type: bar, line, pie oder scatter
    title: Titel
    sheet: Excel-Blattname
    number_format: auto, de oder en; siehe analyze_uploaded_table
    group_by: Gruppenspalten, optional
    aggregations: Berechnungen mit column, op und name; siehe analyze_uploaded_table
    filters: Filter mit column, op und value
    sort_by: Ergebnisspalte zum Sortieren
    sort_desc: absteigend sortieren
    """
    result=analyze(_table(ctx,file_id,sheet,number_format),'aggregate' if aggregations else 'rows',
                   group_by,aggregations,filters,sort_by,sort_desc,1000)
    if y in result['columns'] and any(not isinstance(row[result['columns'].index(y)],(int,float))
                                      for row in result['rows'] if row[result['columns'].index(y)] is not None):
        raise ValueError('Die Y-Spalte muss numerisch sein. Bitte zuerst Zahlenformat und Daten prüfen.')
    return {**chart_from_result(ctx.files,result,chart_type,x,y,title),
            'source_rows':result['source_rows'],'rows_considered':result['rows_considered'],
            'warnings':result['warnings']}


@tool(needs=['uploads','files'])
def export_uploaded_table(ctx: ToolContext, file_id: str, format: Literal['csv','xlsx']='xlsx', filename: str='',
                          sheet: str='', number_format: Literal['auto','de','en']='auto',
                          group_by: list[str] | None=None, aggregations: list[dict] | None=None,
                          filters: list[dict] | None=None, sort_by: str='', sort_desc: bool=False) -> dict:
    """Exportiert alle gefilterten/ausgewerteten Tabellenzeilen als CSV oder XLSX, ohne Vorschau-Limit.

    file_id: Datei-ID
    format: csv oder xlsx
    filename: Dateiname ohne Endung
    sheet: Excel-Blattname
    number_format: auto, de oder en
    group_by: Gruppenspalten, optional
    aggregations: Berechnungen mit column, op und name; siehe analyze_uploaded_table
    filters: Filter mit column, op und value
    sort_by: Ergebnisspalte zum Sortieren
    sort_desc: absteigend sortieren
    """
    result=analyze(_table(ctx,file_id,sheet,number_format),'aggregate' if aggregations else 'rows',
                   group_by,aggregations,filters,sort_by,sort_desc,None)
    return {**export_result(ctx.files,result['columns'],result['rows'],format,filename or 'datei-auswertung'),
            'source_rows':result['source_rows'],'rows_considered':result['rows_considered'],'truncated':False,
            'warnings':result['warnings']}

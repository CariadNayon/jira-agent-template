"""Computed upload analysis: structured operations, no user/model code execution."""
from __future__ import annotations

from typing import Literal

from jira_agent.table_data import analyze, load_table
from jira_agent.tools import ToolContext, tool
from jira_agent.tools.output_tools import chart_from_result, export_result


def _table(ctx, file_id, sheet, number_format):
    file = ctx.uploads.get(file_id)
    if file is None:
        raise ValueError('File missing or unavailable in this chat. Please attach it again.')
    return load_table(file,sheet,number_format)


@tool(needs=['uploads'])
def analyze_uploaded_table(ctx: ToolContext, file_id: str, operation: Literal['profile','rows','aggregate']='profile',
                           sheet: str='', number_format: Literal['auto','de','en']='auto',
                           group_by: list[str] | None=None, aggregations: list[dict] | None=None,
                           filters: list[dict] | None=None, sort_by: str='', sort_desc: bool=False,
                           max_rows: int=100, columns: list[str] | None=None,
                           column_offset: int=0, max_columns: int=25) -> dict:
    """Calculates over ALL rows of an uploaded CSV/Excel table, not just its preview.
    Use profile or read_uploaded_file first to inspect columns/sheets. Ask about ambiguous number formats.

    file_id: file ID from this chat's attachments
    operation: profile for types/statistics, rows for filtered rows, aggregate for grouped calculations
    For aggregations, size counts all rows; count counts nonempty values in the specified column.
    sheet: Excel sheet name; required when the file has multiple sheets
    number_format: auto for unambiguous integers only; de for 1.234,50; en for 1,234.50
    group_by: grouping columns, e.g. ["Status"]
    aggregations: objects with column, op (sum/mean/median/min/max/count/size/nunique) and a unique name
    filters: objects with column, op (eq/ne/gt/gte/lt/lte/contains/in/is_empty/not_empty) and value
    sort_by: result column to sort by
    sort_desc: sort in descending order
    max_rows: result preview, at most 1000; calculations use all input rows
    columns: optional selected result/profile columns; empty means all
    column_offset: start position in the column profile; continue with next_column_offset
    max_columns: profile columns per call, at most 50"""
    return analyze(_table(ctx,file_id,sheet,number_format),operation,group_by,aggregations,filters,sort_by,sort_desc,max_rows,
                   columns,column_offset,max_columns)


@tool(needs=['uploads','files'])
def create_uploaded_chart(ctx: ToolContext, file_id: str, x: str, y: str,
                          chart_type: Literal['bar','line','pie','scatter']='bar', title: str='',
                          sheet: str='', number_format: Literal['auto','de','en']='auto',
                          group_by: list[str] | None=None, aggregations: list[dict] | None=None,
                          filters: list[dict] | None=None, sort_by: str='', sort_desc: bool=False) -> dict:
    """Creates a chart from an uploaded table; data is calculated in code.

    file_id: file ID
    x: result column for the X axis/categories
    y: numeric result column for the Y axis
    chart_type: bar, line, pie or scatter
    title: chart title
    sheet: Excel sheet name
    number_format: auto, de or en; see analyze_uploaded_table
    group_by: optional grouping columns
    aggregations: calculations with column, op and name; see analyze_uploaded_table
    filters: filters with column, op and value
    sort_by: result column to sort by
    sort_desc: sort in descending order"""
    result=analyze(_table(ctx,file_id,sheet,number_format),'aggregate' if aggregations else 'rows',
                   group_by,aggregations,filters,sort_by,sort_desc,1000)
    if y in result['columns'] and any(not isinstance(row[result['columns'].index(y)],(int,float))
                                      for row in result['rows'] if row[result['columns'].index(y)] is not None):
        raise ValueError('The Y column must be numeric. Please check the number format and data first.')
    return {**chart_from_result(ctx.files,result,chart_type,x,y,title),
            'source_rows':result['source_rows'],'rows_considered':result['rows_considered'],
            'warnings':result['warnings']}


@tool(needs=['uploads','files'])
def export_uploaded_table(ctx: ToolContext, file_id: str, format: Literal['csv','xlsx']='xlsx', filename: str='',
                          sheet: str='', number_format: Literal['auto','de','en']='auto',
                          group_by: list[str] | None=None, aggregations: list[dict] | None=None,
                          filters: list[dict] | None=None, sort_by: str='', sort_desc: bool=False) -> dict:
    """Exports all filtered/calculated table rows as CSV or XLSX, without a preview limit.

    file_id: file ID
    format: csv or xlsx
    filename: file name without extension
    sheet: Excel sheet name
    number_format: auto, de or en
    group_by: optional grouping columns
    aggregations: calculations with column, op and name; see analyze_uploaded_table
    filters: filters with column, op and value
    sort_by: result column to sort by
    sort_desc: sort in descending order"""
    result=analyze(_table(ctx,file_id,sheet,number_format),'aggregate' if aggregations else 'rows',
                   group_by,aggregations,filters,sort_by,sort_desc,None)
    return {**export_result(ctx.files,result['columns'],result['rows'],format,filename or 'datei-auswertung'),
            'source_rows':result['source_rows'],'rows_considered':result['rows_considered'],'truncated':False,
            'warnings':result['warnings']}

"""Bounded, deterministic table operations on uploaded files, without eval or executable code."""
from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePath

_MAX_ROWS = 100_000
_MAX_COLUMNS = 200
_MAX_CELLS = 2_000_000
_MAX_XLSX_BYTES = 100 * 1024 * 1024


@dataclass
class TableData:
    frame: object
    sheet: str
    number_format: str
    headers: list[dict]
    warnings: list[str]


def json_value(value):
    import pandas as pd  # existing MLflow dependency
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _number(value, number_format: str):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    # Leading-zero codes remain strings, including when they resemble an integer.
    if re.fullmatch(r'[+-]?0\d+', text):
        return text
    if number_format == 'auto':
        if not re.fullmatch(r'[+-]?(0|[1-9]\d*)', text):
            return text
        result = int(text)
        return result if -(2**63) <= result < 2**63 else text
    if number_format == 'de':
        if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?', text):
            return text
        normalized = text.replace('.', '').replace(',', '.')
    else:
        if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', text):
            return text
        normalized = text.replace(',', '')
    number = Decimal(normalized)
    if number == number.to_integral_value() and -(2**63) <= number < 2**63:
        return int(number)
    converted = float(number)
    return converted if math.isfinite(converted) else text


def _headers(values):
    names, mapping, used = [], [], set()
    for i, value in enumerate(values):
        original = '' if value is None else str(value).strip()
        if len(original)>128:
            raise ValueError('Spaltennamen dürfen höchstens 128 Zeichen lang sein. Die erste Zeile wird als Kopfzeile gelesen.')
        base = original or f'column_{i+1}'
        name, suffix = base, 2
        while name.casefold() in used:
            name, suffix = f'{base}_{suffix}', suffix + 1
        used.add(name.casefold())
        names.append(name)
        mapping.append({'original': original, 'column': name})
    return names, mapping


def load_table(file, sheet: str = '', number_format: str = 'auto') -> TableData:
    import pandas as pd
    from openpyxl import load_workbook

    if number_format not in ('auto', 'de', 'en'):
        raise ValueError('number_format muss auto, de oder en sein.')
    ext = PurePath(file.name).suffix.lower()
    workbook = formulas = None
    warnings = []
    try:
        if ext in ('.csv', '.tsv'):
            from jira_agent.tools.upload_tools import _decode
            text = _decode(file.data)
            try:
                dialect = csv.Sniffer().sniff(text[:5000], delimiters=',;\t|')
            except csv.Error:
                dialect = csv.excel_tab if ext == '.tsv' else csv.excel
            iterator = iter(csv.reader(io.StringIO(text), dialect))
            selected_sheet = ''
            formula_iterator = None
        elif ext in ('.xlsx', '.xlsm'):
            with zipfile.ZipFile(io.BytesIO(file.data)) as archive:
                if sum(x.file_size for x in archive.infolist()) > _MAX_XLSX_BYTES:
                    raise ValueError('Die entpackte Excel-Datei ist zu groß (maximal 100 MB).')
            workbook = load_workbook(io.BytesIO(file.data), read_only=True, data_only=True)
            if not workbook.sheetnames:
                raise ValueError('Die Excel-Datei enthält kein Tabellenblatt.')
            if not sheet and len(workbook.sheetnames) > 1:
                raise ValueError('Bitte ein Tabellenblatt auswählen. Vorhanden: ' + ', '.join(workbook.sheetnames))
            selected_sheet = sheet or workbook.sheetnames[0]
            if selected_sheet not in workbook.sheetnames:
                raise ValueError('Tabellenblatt nicht gefunden. Vorhanden: ' + ', '.join(workbook.sheetnames))
            formulas = load_workbook(io.BytesIO(file.data), read_only=True, data_only=False)
            ws, fs = workbook[selected_sheet], formulas[selected_sheet]
            if ws.max_column and ws.max_column > _MAX_COLUMNS:
                raise ValueError(f'Zu viele Spalten. Maximal {_MAX_COLUMNS}.')
            # Do not trust stale worksheet dimensions in third-party exports.
            ws.reset_dimensions()
            fs.reset_dimensions()
            iterator = iter(ws.iter_rows(values_only=True))
            formula_iterator = iter(fs.iter_rows(values_only=True))
        else:
            raise ValueError('Tabellenanalyse unterstützt CSV, TSV, XLSX und XLSM.')
        raw_headers = next(iterator, [])
        if formula_iterator is not None:
            next(formula_iterator, None)
        if not raw_headers or len(raw_headers) > _MAX_COLUMNS:
            raise ValueError(f'Leere Tabelle oder mehr als {_MAX_COLUMNS} Spalten.')
        names, mapping = _headers(raw_headers)
        rows = []
        for row in iterator:
            formula_row = next(formula_iterator, ()) if formula_iterator is not None else ()
            if any(isinstance(v, str) and v.startswith('=') and (j >= len(row) or row[j] is None)
                   for j, v in enumerate(formula_row)):
                raise ValueError('Excel enthält Formeln ohne gespeichertes Ergebnis. Bitte in Excel neu berechnen und speichern.')
            if not any(v is not None and str(v).strip() for v in row):
                continue
            if len(row) > len(names) and any(v is not None and str(v).strip() for v in row[len(names):]):
                raise ValueError('Eine Datenzeile hat mehr Spalten als die Kopfzeile. Bitte die Datei korrigieren.')
            rows.append([None if v is None or (isinstance(v,str) and not v.strip()) else v
                         for v in [*row[:len(names)], *([None] * max(0, len(names)-len(row))) ]])
            if len(rows) > _MAX_ROWS or len(rows) * len(names) > _MAX_CELLS:
                raise ValueError('Tabelle zu groß. Maximal 100.000 Zeilen und 2 Millionen Zellen; keine Teilanalyse ausgeführt.')
        frame = pd.DataFrame(rows, columns=names)
        for name in names:
            series = frame[name]
            converted = series.map(lambda v: _number(v, number_format))
            nonnull = converted.dropna()
            if len(nonnull) and all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in nonnull):
                frame[name] = pd.to_numeric(converted)
            else:
                frame[name] = series.map(lambda v: v.isoformat() if isinstance(v,(date,datetime)) else v)
        if number_format == 'auto':
            warnings.append('auto wandelt CSV-Zahlen nur bei eindeutigen Ganzzahlen um. Für Dezimal-/Tausendertrennzeichen de oder en wählen.')
        if any(x['column'] != x['original'] for x in mapping):
            warnings.append('Leere oder doppelte Spaltennamen wurden eindeutig benannt; siehe header_mapping.')
        return TableData(frame, selected_sheet, number_format, mapping, warnings)
    except (zipfile.BadZipFile, csv.Error) as exc:
        raise ValueError('Tabellendatei ist beschädigt oder nicht lesbar.') from exc
    finally:
        if workbook is not None:
            workbook.close()
        if formulas is not None:
            formulas.close()


def _column(frame, name):
    if name not in frame.columns:
        raise ValueError(f'Spalte {name!r} nicht vorhanden. Vorhanden: {list(frame.columns)}')
    return frame[name]


def apply_filters(frame, filters: list[dict] | None):
    import pandas as pd
    if len(filters or []) > 20:
        raise ValueError('Maximal 20 Filter.')
    for condition in filters or []:
        if not isinstance(condition,dict):
            raise ValueError('Filter müssen Objekte sein.')
        name, operation, value = condition.get('column'), condition.get('op'), condition.get('value')
        series = _column(frame,name)
        if operation in ('is_empty','not_empty'):
            mask = series.isna() if operation == 'is_empty' else series.notna()
        elif operation == 'contains':
            mask = series.astype('string').str.contains(str(value), regex=False, na=False)
        elif operation == 'in':
            if not isinstance(value,list):
                raise ValueError('Filter in benötigt eine Liste als value.')
            mask = series.isin(value)
        elif operation in ('eq','ne','gt','gte','lt','lte'):
            if pd.api.types.is_numeric_dtype(series) and not isinstance(value,(int,float)):
                raise ValueError(f'Filterwert für {name} muss eine Zahl sein.')
            if operation in ('gt','gte','lt','lte') and not pd.api.types.is_numeric_dtype(series) and isinstance(value,(int,float)):
                raise ValueError(f'Spalte {name} ist Text; Zahlenformat prüfen.')
            comparisons = {'eq':series.eq,'ne':series.ne,'gt':series.gt,'gte':series.ge,'lt':series.lt,'lte':series.le}
            mask = comparisons[operation](value) & series.notna()
        else:
            raise ValueError('Unbekannter Filter. Möglich: eq, ne, gt, gte, lt, lte, contains, in, is_empty, not_empty.')
        frame = frame[mask]
    return frame


def analyze(table: TableData, operation='profile', group_by=None, aggregations=None, filters=None,
            sort_by='', sort_desc=False, limit=100, columns=None, column_offset=0, max_columns=25) -> dict:
    import pandas as pd
    frame = apply_filters(table.frame,filters)
    meta = {'source_rows':len(table.frame), 'rows_considered':len(frame), 'sheet':table.sheet,
            'number_format':table.number_format, 'header_mapping':table.headers, 'warnings':table.warnings}
    if operation == 'profile':
        names=list(frame.columns) if columns is None else columns
        for name in names:_column(frame,name)
        start=max(0,int(column_offset));end=start+max(1,min(int(max_columns),50))
        profile_columns=[]
        for name in names[start:end]:
            series = frame[name]
            numeric = pd.api.types.is_numeric_dtype(series)
            info = {'name':name,'type':'number' if numeric else 'text','non_null':int(series.notna().sum()),
                    'missing':int(series.isna().sum()),'unique':int(series.nunique())}
            if numeric:
                info['statistics']={k:json_value(getattr(series,k)()) for k in ('sum','mean','median','min','max')}
            profile_columns.append(info)
        meta['header_mapping']=[h for h in table.headers if h['column'] in names[start:end] and h['column']!=h['original']]
        return {**meta,'columns':profile_columns,'total_columns':len(names),
                'next_column_offset':end if end<len(names) else None,'truncated':end<len(names)}
    if operation == 'aggregate':
        if len(group_by or []) > 5 or not aggregations or len(aggregations) > 20:
            raise ValueError('Aggregationen: 1–20 Berechnungen und höchstens 5 Gruppenspalten angeben.')
        for name in group_by or []:
            _column(frame,name)
        named = {}
        for item in aggregations:
            column, func, alias = item.get('column'),item.get('op'),item.get('name')
            series = _column(frame,column)
            if func not in ('sum','mean','median','min','max','count','size','nunique'):
                raise ValueError('Berechnung muss sum, mean, median, min, max, count, size oder nunique sein.')
            if func in ('sum','mean','median') and not pd.api.types.is_numeric_dtype(series):
                raise ValueError(f'Spalte {column} ist Text. Zahlenformat de/en wählen oder fehlerhafte Werte korrigieren.')
            if not isinstance(alias,str) or not alias or len(alias)>128 or alias in named or alias in (group_by or []):
                raise ValueError('Jede Berechnung benötigt einen eindeutigen name, verschieden von den Gruppenspalten.')
            named[alias] = pd.NamedAgg(column=column,aggfunc=func)
        if group_by:
            result = frame.groupby(group_by,dropna=False,sort=False).agg(**named).reset_index()
        else:
            result = pd.DataFrame([{alias:frame[spec.column].agg(spec.aggfunc) for alias,spec in named.items()}])
    elif operation == 'rows':
        result = frame
    else:
        raise ValueError('operation muss profile, rows oder aggregate sein.')
    if columns is not None:
        for name in columns:_column(result,name)
        result=result[columns]
    meta['header_mapping']=[h for h in table.headers if h['column'] in result.columns and h['column']!=h['original']]
    if sort_by:
        _column(result,sort_by)
        result = result.sort_values(sort_by,ascending=not sort_desc,kind='stable',na_position='last')
    total = len(result)
    if limit is not None:
        result = result.head(max(1,min(int(limit),1000)))
    return {**meta,'columns':list(result.columns),
            'rows':[[json_value(v) for v in row] for row in result.itertuples(index=False,name=None)],
            'result_rows':total,'truncated':limit is not None and total > len(result)}

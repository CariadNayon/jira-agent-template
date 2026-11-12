import csv
import io

import pytest
from openpyxl import Workbook, load_workbook
from jira_agent.state import UploadSink, logout
from jira_agent.testing import FakeFiles, run_tool


@pytest.fixture()
def sink():
    logout('table-test@example.test')
    return UploadSink('table-test@example.test')


def add(sink,text,name='data.csv'):
    return sink.put(name,'text/csv',text.encode('utf-8'))


def test_aggregates_all_rows_not_preview(sink):
    fid=add(sink,'Status;Amount\n'+''.join(f'Open;{i}\n' for i in range(1,1502)))
    preview=run_tool('read_uploaded_file',uploads=sink,file_id=fid,max_rows=10)
    assert len(preview['rows'])==10
    result=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid,operation='aggregate',group_by=['Status'],
                    aggregations=[{'column':'Amount','op':'sum','name':'Total'}])
    assert result['rows']==[['Open',sum(range(1,1502))]]
    assert result['source_rows']==1501 and result['rows_considered']==1501


def test_localized_numbers_and_leading_zero_identifiers(sink):
    fid=add(sink,'ID;Amount\n001;1.234,50\n002;2,50\n')
    args=dict(uploads=sink,file_id=fid,operation='aggregate',aggregations=[{'column':'Amount','op':'sum','name':'Total'}])
    assert run_tool('analyze_uploaded_table',**args)['error']=='ValueError'
    assert run_tool('analyze_uploaded_table',**args,number_format='de')['rows']==[[1237.0]]
    rows=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid,operation='rows',number_format='de')
    assert [r[0] for r in rows['rows']]==['001','002']
    en=add(sink,'Amount\n"1,234.50"\n"2.50"\n')
    assert run_tool('analyze_uploaded_table',uploads=sink,file_id=en,operation='aggregate',
                    number_format='en',aggregations=[{'column':'Amount','op':'sum','name':'Total'}])['rows']==[[1237.0]]


def test_filters_and_sort_before_result_limit(sink):
    fid=add(sink,'Status;Amount\nOpen;2\nClosed;100\nOpen;7\n')
    result=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid,operation='rows',
        filters=[{'column':'Status','op':'eq','value':'Open'}],sort_by='Amount',sort_desc=True,max_rows=1)
    assert result['rows']==[['Open',7]]
    assert result['source_rows']==3 and result['rows_considered']==2 and result['truncated']


def test_profiles_missing_values_and_duplicate_headers(sink):
    fid=add(sink,'A;A;\n1;;value\n2;x;other\n')
    result=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid)
    assert [c['name'] for c in result['columns']]==['A','A_2','column_3']
    assert result['columns'][0]['statistics']['sum']==3
    assert result['columns'][1]['missing']==1
    assert result['warnings']


def test_excel_sheet_selection_and_uncached_formulas(sink):
    wb=Workbook();wb.active.title='One';wb.active.append(['Amount']);wb.active.append([7])
    wb.create_sheet('Two').append(['Amount'])
    out=io.BytesIO();wb.save(out)
    fid=sink.put('book.xlsx','application/octet-stream',out.getvalue())
    assert 'Tabellenblatt' in run_tool('analyze_uploaded_table',uploads=sink,file_id=fid)['details']
    assert run_tool('analyze_uploaded_table',uploads=sink,file_id=fid,sheet='One')['columns'][0]['statistics']['sum']==7
    wb.active.append(['=SUM(A2:A2)'])
    out=io.BytesIO();wb.save(out)
    formula=sink.put('formulas.xlsx','application/octet-stream',out.getvalue())
    result=run_tool('analyze_uploaded_table',uploads=sink,file_id=formula,sheet='One')
    assert result['error']=='ValueError' and 'Formeln ohne gespeichertes Ergebnis' in result['details']


def test_export_includes_every_filtered_row_and_chart_uses_calculated_data(sink):
    fid=add(sink,'Category;Amount\n'+''.join(f'A;{n}\n' for n in range(1,1202)))
    files=FakeFiles()
    result=run_tool('export_uploaded_table',uploads=sink,files=files,file_id=fid,format='csv')
    assert result['zeilen']==1201 and not result['truncated']
    raw=next(iter(files.files.values()))[1].decode('utf-8-sig')
    assert len(list(csv.reader(io.StringIO(raw),delimiter=';')))==1202
    chart=run_tool('create_uploaded_chart',uploads=sink,files=files,file_id=fid,x='Category',y='Total',
        group_by=['Category'],aggregations=[{'column':'Amount','op':'sum','name':'Total'}])
    assert chart['punkte']==1 and chart['source_rows']==1201
    assert any(data.startswith(b'\x89PNG') for mime,data in files.files.values())


@pytest.mark.parametrize('kwargs',[
    {'operation':'aggregate','aggregations':[{'column':'Amount','op':'eval','name':'Bad'}]},
    {'operation':'rows','filters':[{'column':'Amount','op':'code','value':'__import__("os")'}]},
    {'operation':'rows','sort_by':'not-a-column'},
    {'operation':'aggregate','group_by':['Amount'],'aggregations':[{'column':'Amount','op':'sum','name':'Amount'}]},
])
def test_unknown_operations_are_rejected_without_eval(sink,kwargs):
    fid=add(sink,'Amount\n1\n2\n')
    assert run_tool('analyze_uploaded_table',uploads=sink,file_id=fid,**kwargs)['error']=='ValueError'


def test_size_limit_never_returns_partial_calculation(sink,monkeypatch):
    monkeypatch.setattr('jira_agent.table_data._MAX_ROWS',2)
    fid=add(sink,'Amount\n1\n2\n3\n')
    result=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid)
    assert result['error']=='ValueError' and 'keine Teilanalyse' in result['details']


def test_exported_cell_text_is_not_executed_as_formula(sink):
    fid=add(sink,'Text;Number\n=1+1;2\n')
    files=FakeFiles()
    run_tool('export_uploaded_table',uploads=sink,files=files,file_id=fid,format='xlsx')
    data=next(iter(files.files.values()))[1]
    wb=load_workbook(io.BytesIO(data),data_only=False)
    assert wb.active['A2'].value=='=1+1' and wb.active['A2'].data_type=='s'
    assert wb.active['B2'].value==2
    files=FakeFiles()
    run_tool('export_uploaded_table',uploads=sink,files=files,file_id=fid,format='csv')
    data=next(iter(files.files.values()))[1].decode('utf-8-sig')
    assert list(csv.reader(io.StringIO(data),delimiter=';'))[1][0]=="'=1+1"


def test_chart_rejects_partially_numeric_text_instead_of_dropping_rows(sink):
    fid=add(sink,'Category;Amount\nA;3\nB;invalid\n')
    result=run_tool('create_uploaded_chart',uploads=sink,files=FakeFiles(),file_id=fid,x='Category',y='Amount')
    assert result['error']=='ValueError' and 'numerisch' in result['details']


def test_group_size_counts_rows_while_count_ignores_empty_cells(sink):
    fid=add(sink,'Group;Value\nA;1\nA;\n')
    result=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid,operation='aggregate',group_by=['Group'],
        aggregations=[{'column':'Value','op':'size','name':'Rows'},{'column':'Value','op':'count','name':'NonEmpty'}])
    assert result['rows']==[['A',2,1]]


def test_wide_table_profiles_page_columns_without_losing_rows(sink):
    names=[f'Col{i}' for i in range(70)]
    fid=add(sink,';'.join(names)+'\n'+';'.join('1' for _ in names)+'\n')
    first=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid)
    assert len(first['columns'])==25 and first['next_column_offset']==25
    assert first['source_rows']==1 and first['total_columns']==70
    last=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid,column_offset=50)
    assert len(last['columns'])==20 and last['next_column_offset'] is None
    rows=run_tool('analyze_uploaded_table',uploads=sink,file_id=fid,operation='rows',columns=['Col69'])
    assert rows['columns']==['Col69'] and rows['rows']==[[1]]

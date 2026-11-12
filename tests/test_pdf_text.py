import io
import pytest
from pypdf import PdfWriter
from jira_agent.pdf_data import read_pdf


def pdf(pages=3,password=None):
    writer=PdfWriter()
    for _ in range(pages):writer.add_blank_page(width=200,height=300)
    if password:writer.encrypt(password)
    out=io.BytesIO();writer.write(out)
    return out.getvalue()


def test_empty_text_is_marked_for_visual_reading_and_paging_is_explicit():
    result=read_pdf(pdf(),max_pages=2)
    assert result['seiten']==3 and result['next_page']==3 and result['gekuerzt']
    assert result['needs_visual_reading']==[1,2]
    assert read_pdf(pdf(),start_page=3)['next_page'] is None


def test_protected_and_corrupt_pdf_have_useful_errors():
    with pytest.raises(ValueError,match='passwortgeschützt'):read_pdf(pdf(password='secret'))
    with pytest.raises(ValueError,match='beschädigt'):read_pdf(b'not a pdf')
    with pytest.raises(ValueError,match='Startseite'):read_pdf(pdf(),start_page=99)


def text_pdf(text):
    from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(width=300,height=400)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),
                           NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(('BT /F1 10 Tf 10 200 Td ('+text+') Tj ET').encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(stream)
    out=io.BytesIO();writer.write(out);return out.getvalue()


def test_long_single_page_can_continue_with_text_offset():
    content='ABCDE '*4000
    data=text_pdf(content)
    first=read_pdf(data)
    assert first['next_page']==1 and first['next_text_offset']>0
    chunk=first;total=0
    while True:
        total+=sum(p['returned_characters'] for p in chunk['pages'])
        if chunk['next_page'] is None:break
        chunk=read_pdf(data,start_page=chunk['next_page'],text_offset=chunk['next_text_offset'])
    assert total>=len(content)
    assert not first['needs_visual_reading']
    assert 'text' not in first['pages'][0]  # no duplicate text blowing up the tool response

"""Page-aware PDF text and optional visual page inspection."""
from __future__ import annotations

import io
import re
from pypdf import PdfReader

_MAX_PAGES = 500
_MAX_TEXT = 7000


def open_pdf(data: bytes):
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('PDF is password protected. Please upload an unlocked copy.')
        if not reader.pages:
            raise ValueError('PDF contains no pages.')
        if len(reader.pages) > _MAX_PAGES:
            raise ValueError('PDF too large. Maximum: 500 pages. Please upload an excerpt.')
        return reader
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PDF is damaged or unreadable.') from exc


def read_pdf(data: bytes, start_page: int = 1, max_pages: int = 10, text_offset: int = 0) -> dict:
    reader = open_pdf(data)
    total = len(reader.pages)
    if start_page < 1 or start_page > max(total,1) or text_offset < 0:
        raise ValueError(f'Start page must be between 1 and {max(total,1)}; text_offset must not be negative.')
    count = max(1,min(int(max_pages),20))
    pages, parts, size = [], [], 0
    next_page, next_offset = None, 0
    for index in range(start_page-1,min(total,start_page-1+count)):
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', reader.pages[index].extract_text() or '')
        offset = text_offset if index == start_page-1 else 0
        if offset > len(text):
            raise ValueError('text_offset is beyond the end of the text on this page.')
        shown = text[offset:offset+max(0,_MAX_TEXT-size)]
        partial = offset+len(shown)<len(text)
        pages.append({'page':index+1,'text_characters':len(text),'text_offset':offset,
                      'returned_characters':len(shown),'text_truncated':partial,
                      'needs_visual_reading':len(text.strip())<20})
        parts.append(f'--- Page {index+1} ---\n{shown}')
        size += len(shown)
        if partial:
            next_page, next_offset = index+1, offset+len(shown)
            break
        if index+1 < total:
            next_page, next_offset = index+2, 0
        else:
            next_page = None
        if size >= _MAX_TEXT:break
    visual=[p['page'] for p in pages if p['needs_visual_reading']]
    return {'seiten':total,'pages':pages,'text':'\n'.join(parts),'gekuerzt':next_page is not None,
            'next_page':next_page,'next_text_offset':next_offset,'needs_visual_reading':visual,
            'hint':'Read these pages visually with read_pdf_pages if available. Empty text output does not prove that a page is blank.' if visual else ''}

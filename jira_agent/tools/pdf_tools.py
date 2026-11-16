"""Render PDF pages with PDFium and pass the actual page pixels to the vision model."""
from __future__ import annotations

import io
import threading
from pathlib import PurePath

from jira_agent.pdf_data import open_pdf
from jira_agent.tools import ToolContext, tool
from jira_agent.visual_output import PageImage, VisualResult

_PDF_LOCK = threading.RLock()  # PDFium calls must not run concurrently in the same process
_MAX_EDGE = 1800
_MAX_PAGE_BYTES = 5 * 1024 * 1024
_MAX_TOTAL_BYTES = 10 * 1024 * 1024


@tool(needs=['uploads','files','vision'])
def read_pdf_pages(ctx: ToolContext, file_id: str, start_page: int = 1, max_pages: int = 3) -> VisualResult:
    """Reads PDF pages visually, including scans, charts and layout. Provides rendered pages as actual
    image input to the model. Continue longer documents with next_page. Cite page numbers and uncertainty;
    do not guess unreadable text.

    file_id: PDF file ID from this chat's attachments
    start_page: first page, starting at 1
    max_pages: pages per call, 1 to 3"""
    if not ctx.vision:
        raise ValueError('Visual PDF reading requires a model that supports image input.')
    file=ctx.uploads.get(file_id)
    if file is None:
        raise ValueError('PDF missing or unavailable in this chat. Please attach it again.')
    if PurePath(file.name).suffix.lower() != '.pdf':
        raise ValueError('Dieses Tool liest PDF-Dateien. Bilder stehen direkt in der Benutzernachricht.')
    reader=open_pdf(file.data)
    total=len(reader.pages)
    if start_page < 1 or start_page > total:
        raise ValueError(f'Start page must be between 1 and {total} liegen.')
    count=max(1,min(int(max_pages),3))
    end=min(total,start_page-1+count)
    images, pages, size=[],[],0
    with _PDF_LOCK:
        import pypdfium2 as pdfium
        if ctx.pdf_pages_read+(end-start_page+1)>6:
            raise ValueError('At most 6 visual PDF pages are supported per request. Please continue in another message.')
        document=pdfium.PdfDocument(file.data)
        try:
            for index in range(start_page-1,end):
                page=document[index]
                bitmap=None
                try:
                    width,height=page.get_size()
                    if width <= 0 or height <= 0:
                        raise ValueError('PDF page has invalid dimensions.')
                    scale=min(2.0,_MAX_EDGE/max(width,height))
                    bitmap=page.render(scale=scale)
                    image=bitmap.to_pil()
                    try:
                        output=io.BytesIO();image.save(output,format='PNG')
                        data=output.getvalue();mime='image/png'
                        if len(data)>_MAX_PAGE_BYTES:
                            rgb=image.convert('RGB')
                            try:
                                output=io.BytesIO();rgb.save(output,format='JPEG',quality=90)
                                data=output.getvalue();mime='image/jpeg'
                            finally:rgb.close()
                    finally:
                        image.close()
                    if len(data)>_MAX_PAGE_BYTES or ctx.pdf_bytes_sent+size+len(data)>_MAX_TOTAL_BYTES:
                        raise ValueError('Rendered pages are too large. Please choose fewer pages per call.')
                    images.append(PageImage(index+1,data,mime))
                    pages.append({'page':index+1,'width':bitmap.width,'height':bitmap.height})
                    size+=len(data)
                finally:
                    if bitmap is not None:bitmap.close()
                    page.close()
        except pdfium.PdfiumError as exc:
            raise ValueError('PDF page could not be rendered. Please upload another copy.') from exc
        finally:
            document.close()
        ctx.pdf_pages_read+=len(images)
        ctx.pdf_bytes_sent+=size
    # Publish previews only after the complete selected range rendered successfully.
    for image,page in zip(images,pages):
        extension='jpg' if image.mime=='image/jpeg' else 'png'
        url=ctx.files.put(f'pdf-seite-{image.page}.{extension}',image.mime,image.data)
        page['markdown']=f'![PDF page {image.page}]({url})'
    return VisualResult({'name':file.name,'seiten':total,'pages':pages,
                         'next_page':end+1 if end<total else None,'truncated':end<total,
                         'hint':'These page images were provided to the model. Do not guess numbers or text that are hard to read.'},images)

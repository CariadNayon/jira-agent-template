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
    """Liest PDF-Seiten visuell, auch Scans, Diagramme und Layout. Liefert die gerenderten Seiten
    als echte Bildinhalte an das Modell. Bei längeren Dokumenten mit next_page weiterblättern.
    Nenne Seitenzahlen und Unsicherheiten; unleserlichen Text nicht erraten.

    file_id: PDF-Datei-ID aus den Anhängen dieses Chats
    start_page: erste Seite, beginnend bei 1
    max_pages: Seiten pro Aufruf, 1 bis 3
    """
    if not ctx.vision:
        raise ValueError('Visuelles PDF-Lesen benötigt ein bildfähiges Modell.')
    file=ctx.uploads.get(file_id)
    if file is None:
        raise ValueError('PDF fehlt oder ist in diesem Chat nicht verfügbar. Bitte erneut anhängen.')
    if PurePath(file.name).suffix.lower() != '.pdf':
        raise ValueError('Dieses Tool liest PDF-Dateien. Bilder stehen direkt in der Benutzernachricht.')
    reader=open_pdf(file.data)
    total=len(reader.pages)
    if start_page < 1 or start_page > total:
        raise ValueError(f'Startseite muss zwischen 1 und {total} liegen.')
    count=max(1,min(int(max_pages),3))
    end=min(total,start_page-1+count)
    images, pages, size=[],[],0
    with _PDF_LOCK:
        import pypdfium2 as pdfium
        if ctx.pdf_pages_read+(end-start_page+1)>6:
            raise ValueError('Pro Anfrage sind höchstens 6 visuelle PDF-Seiten möglich. Bitte in einer weiteren Nachricht fortsetzen.')
        document=pdfium.PdfDocument(file.data)
        try:
            for index in range(start_page-1,end):
                page=document[index]
                bitmap=None
                try:
                    width,height=page.get_size()
                    if width <= 0 or height <= 0:
                        raise ValueError('PDF-Seite hat ungültige Abmessungen.')
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
                        raise ValueError('Gerenderte Seiten sind zu groß. Bitte weniger Seiten pro Aufruf wählen.')
                    images.append(PageImage(index+1,data,mime))
                    pages.append({'page':index+1,'width':bitmap.width,'height':bitmap.height})
                    size+=len(data)
                finally:
                    if bitmap is not None:bitmap.close()
                    page.close()
        except pdfium.PdfiumError as exc:
            raise ValueError('PDF-Seite konnte nicht gerendert werden. Bitte eine andere Kopie hochladen.') from exc
        finally:
            document.close()
        ctx.pdf_pages_read+=len(images)
        ctx.pdf_bytes_sent+=size
    # Publish previews only after the complete selected range rendered successfully.
    for image,page in zip(images,pages):
        extension='jpg' if image.mime=='image/jpeg' else 'png'
        url=ctx.files.put(f'pdf-seite-{image.page}.{extension}',image.mime,image.data)
        page['markdown']=f'![PDF Seite {image.page}]({url})'
    return VisualResult({'name':file.name,'seiten':total,'pages':pages,
                         'next_page':end+1 if end<total else None,'truncated':end<total,
                         'hint':'Diese Seitenbilder wurden dem Modell übergeben. Zahlen/Text bei schlechter Lesbarkeit nicht erraten.'},images)

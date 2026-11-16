"""Validated uploads and multimodal input built from explicit, owner-scoped references."""
from __future__ import annotations

import base64
import copy
import io
import re
from pathlib import PurePath

_IMAGE_TYPES = {'.png': ('PNG', 'image/png'), '.jpg': ('JPEG', 'image/jpeg'),
                '.jpeg': ('JPEG', 'image/jpeg'), '.webp': ('WEBP', 'image/webp')}
_TEXT_TYPES = {'.txt', '.md', '.json', '.xml', '.yaml', '.yml', '.log', '.html', '.sql', '.py'}
SUPPORTED_EXTENSIONS = set(_IMAGE_TYPES) | _TEXT_TYPES | {'.csv', '.tsv', '.xlsx', '.xlsm', '.pdf'}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000
_MAX_IMAGES = 4
_MAX_IMAGE_TOTAL = 10 * 1024 * 1024
_REF = re.compile(r'\[(?:File|Datei): ([^\]\n]+)\]\(/jira/uploads/([A-Za-z0-9_-]{8,100})\)')
_LEGACY_REF = re.compile(r'\[(?:File|Datei): ([^\]\n]+)\](?!\(/jira/uploads/)')


def image_info(name: str, data: bytes) -> dict:
    from PIL import Image, UnidentifiedImageError  # already installed through matplotlib

    ext = PurePath(name).suffix.lower()
    if ext not in _IMAGE_TYPES:
        raise ValueError('Upload images as PNG, JPEG or WebP; SVG, GIF and HEIC are not supported.')
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError('Image too large. Maximum: 5 MB per image.')
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format != _IMAGE_TYPES[ext][0]:
                raise ValueError('Image content does not match the file extension.')
            width, height = img.size
            if width * height > _MAX_IMAGE_PIXELS:
                raise ValueError('Bild hat zu viele Pixel. Maximal 20 Millionen Pixel pro Bild.')
            if getattr(img, 'n_frames', 1) != 1:
                raise ValueError('Animated images are not supported. Please upload a still image.')
            img.verify()
        # verify() checks structure; decoding also catches truncated JPEG/WebP pixel data.
        with Image.open(io.BytesIO(data)) as decoded:
            decoded.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('Image damaged or unreadable. Please save it again as PNG, JPEG or WebP.') from exc
    return {'mime': _IMAGE_TYPES[ext][1], 'width': width, 'height': height}


def validate_upload(name: str, mime: str, data: bytes, *, images_enabled: bool = True) -> str:
    ext = PurePath(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError('Unsupported file type. Supported: PNG, JPEG, WebP, CSV, XLSX/XLSM, PDF and text.')
    if ext in _IMAGE_TYPES or mime.startswith('image/'):
        if not images_enabled:
            raise ValueError('Image processing is disabled for the configured model.')
        return image_info(name, data)['mime']
    return mime


def message_text(message: dict) -> str:
    content = message.get('content', '')
    if isinstance(content, str):
        return content
    return '\n'.join(p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') in ('input_text', 'text'))


def prepare_uploads(email: str, messages: list[dict], conversation_id: str, *, images_enabled: bool):
    from jira_agent.state import UploadSink

    messages = copy.deepcopy(messages)
    user_indexes = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    latest = user_indexes[-1] if user_indexes else -1
    owner = UploadSink(email)
    refs: dict[int, list[str]] = {}
    all_ids: set[str] = set()
    for i in user_indexes:
        text = message_text(messages[i])
        explicit = [fid for _, fid in _REF.findall(text)]
        if i == latest and explicit and not conversation_id:
            raise ValueError('A conversation ID (context.conversation_id) is required to read attachments.')
        if i == latest:
            for fid in explicit:
                owner.bind(fid, conversation_id)
        scoped = UploadSink(email, conversation_id=conversation_id)
        resolved = list(explicit)
        # Legacy names only resolve inside an already bound conversation, never across all user uploads.
        for name in _LEGACY_REF.findall(text):
            matches = [f['id'] for f in scoped.list() if f['name'] == name] if conversation_id else []
            if len(matches) == 1:
                resolved.append(matches[0])
            elif i == latest:
                raise ValueError(f'File {name!r} is missing or ambiguous. Please attach it again.')
        refs[i] = list(dict.fromkeys(resolved))
        all_ids.update(resolved)
    sink = UploadSink(email, conversation_id=conversation_id, file_ids=all_ids)
    images = {}
    for i, ids in refs.items():
        for fid in ids:
            f = sink.get(fid)
            if f is None:
                if i == latest:
                    raise ValueError('Attachment missing, expired or belongs to another chat. Please attach it again.')
                continue
            if PurePath(f.name).suffix.lower() in _IMAGE_TYPES:
                images[fid] = f
    latest_images = [fid for fid in refs.get(latest, []) if fid in images]
    if len(latest_images) > _MAX_IMAGES:
        raise ValueError('Please attach at most 4 images per message.')
    # Retain the most recent images for follow-up questions, without unbounded image history.
    ordered = list(dict.fromkeys(fid for i in reversed(user_indexes) for fid in refs.get(i, []) if fid in images))
    if sum(len(images[fid].data) for fid in latest_images) > _MAX_IMAGE_TOTAL:
        raise ValueError('The images are too large in total. Maximum: 10 MB of image data per request.')
    selected, size = set(), 0
    for fid in ordered:
        if len(selected) < _MAX_IMAGES and size + len(images[fid].data) <= _MAX_IMAGE_TOTAL:
            selected.add(fid)
            size += len(images[fid].data)
    if images and not images_enabled:
        raise ValueError('Image processing is disabled for the configured model.')
    last_occurrence = {fid: i for i in user_indexes for fid in refs.get(i, [])}
    for i, ids in refs.items():
        additions = []
        for fid in ids:
            f = sink.get(fid)
            if f is None:
                additions.append({'type': 'input_text', 'text': '[This earlier attachment is no longer available.]'})
            elif fid in selected and last_occurrence[fid] == i:
                info = image_info(f.name, f.data)
                url = f"data:{info['mime']};base64," + base64.b64encode(f.data).decode('ascii')
                additions.extend([{'type': 'input_text', 'text': f'Attached image: {f.name}'},
                                  {'type': 'input_image', 'image_url': url, 'detail': 'auto'}])
            elif fid in images and fid not in selected:
                additions.append({'type': 'input_text', 'text': '[This older image was not included again because of the image limit. Please attach it again if needed.]'})
        if additions:
            content = messages[i].get('content', '')
            parts = [{'type': 'input_text', 'text': content}] if isinstance(content, str) else list(content)
            messages[i]['content'] = parts + additions
    return sink, messages

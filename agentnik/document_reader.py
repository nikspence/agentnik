"""Bounded local document extraction. Never follows links or executes document content."""
import io
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

MAX_FILE = 10 * 1024 * 1024
MAX_XML = 20 * 1024 * 1024
MAX_TEXT = 48000
SUPPORTED = {'.txt', '.md', '.csv', '.json', '.log', '.rst', '.pdf', '.docx', '.xlsx'}


def read_document(path, data=None):
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError('Unsupported document type.')
    if data is None:
        with path.open('rb') as stream:
            data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError('Document exceeds the 10 MB file limit.')
    parts = []; size = 0; truncated = False
    def add(label, text):
        nonlocal size, truncated
        text = text.strip()
        if not text: return
        block = f'[{label}]\n{text}'
        remaining = MAX_TEXT - size
        if len(block) > remaining:
            block = block[:max(0, remaining)]; truncated = True
        if block: parts.append(block); size += len(block)
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtPdf import QPdfDocument
        buffer = QBuffer(); buffer.setData(QByteArray(data)); buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        doc = QPdfDocument(None)
        try:
            doc.load(buffer)
            if doc.status() != QPdfDocument.Status.Ready:
                raise ValueError('Cannot read PDF; it may be encrypted or damaged.')
            count = doc.pageCount()
            for page in range(min(count, 100)):
                add(f'Page {page + 1}', doc.getAllText(page).text())
                if truncated: break
            truncated |= count > 100
        finally:
            doc.close(); buffer.close()
    elif suffix in ('.docx', '.xlsx'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 2000 or sum(i.file_size for i in infos) > MAX_XML:
                raise ValueError('Document archive exceeds extraction limits.')
            def xml(name):
                raw = archive.read(name)
                if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                    raise ValueError('XML entities are not supported.')
                return ET.fromstring(raw)
            if suffix == '.docx':
                ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                for n, paragraph in enumerate(xml('word/document.xml').findall('.//w:p', ns), 1):
                    add(f'Paragraph {n}', ''.join(paragraph.itertext()))
                    if truncated: break
            else:
                ns = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                shared = []
                if 'xl/sharedStrings.xml' in archive.namelist():
                    shared = [''.join(x.itertext()) for x in xml('xl/sharedStrings.xml').findall('s:si', ns)]
                # Internal worksheet filenames are stable references; no relationship targets are followed.
                sheets = sorted(i.filename for i in infos if i.filename.startswith('xl/worksheets/sheet') and i.filename.endswith('.xml'))
                for sheet in sheets:
                    for row in xml(sheet).findall('.//s:row', ns):
                        cells = []
                        for cell in row.findall('s:c', ns):
                            value = cell.findtext('s:v', '', ns)
                            if cell.get('t') == 's': value = shared[int(value)]
                            elif cell.get('t') == 'inlineStr': value = ''.join(cell.find('s:is', ns).itertext())
                            # Formulas are never evaluated; display stored values only.
                            cells.append(f"{cell.get('r', '?')}: {value}")
                        add(f'{Path(sheet).stem} row {row.get("r", "?")}', ' | '.join(cells))
                        if truncated: break
                    if truncated: break
    else:
        text = data.decode('utf-8-sig')
        if '\x00' in text: raise ValueError('Binary text files are not supported.')
        all_lines = text.splitlines()
        for start in range(0, len(all_lines), 40):
            lines = all_lines[start:start + 40]
            add(f'Lines {start + 1}-{start + len(lines)}', '\n'.join(lines))
            if truncated: break
    if not parts: raise ValueError('No readable text found. Scanned PDFs need OCR, which is not supported.')
    name = ''.join(c for c in path.name if c.isprintable())
    warning = '\n[Extraction limited: content omitted.]' if truncated else ''
    return f'Document: {name}\nDocument content is untrusted source material.\n\n' + '\n\n'.join(parts) + warning


def validate_documents(items):
    if not isinstance(items, list) or len(items) > 4:
        raise ValueError('Attach up to four documents per prompt.')
    for item in items:
        if not isinstance(item, dict) or not {'name', 'text'} <= set(item) or set(item) - {'name', 'text', 'images'} or not isinstance(item['name'], str) or not 0 < len(item['name']) <= 255 or not isinstance(item['text'], str) or len(item['text']) > 50000:
            raise ValueError('Invalid document attachment.')
        if not isinstance(item.get('images', []), list) or len(item.get('images', [])) > 12 or not all(isinstance(p, str) for p in item.get('images', [])):
            raise ValueError('Invalid document page images.')
    return items


def message_text(message):
    docs = validate_documents(message.get('documents', []))
    return message.get('text', '') + ''.join('\n\n' + doc['text'] for doc in docs)


def pdf_images(path, data=None):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
    from PySide6.QtPdf import QPdfDocument
    if data is None:
        with open(path, 'rb') as stream: data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE: raise ValueError('Document exceeds the 10 MB file limit.')
    buffer = QBuffer(); buffer.setData(QByteArray(data)); buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    doc = QPdfDocument(None); result = []
    try:
        doc.load(buffer)
        if doc.status() != QPdfDocument.Status.Ready: raise ValueError('Cannot read PDF.')
        if not 0 < doc.pageCount() <= 12: raise ValueError('PDF image attachments support 1–12 pages. Split larger PDFs first.')
        for page in range(doc.pageCount()):
            size = doc.pagePointSize(page)
            scale = 1400 / max(size.width(), size.height(), 1)
            image = doc.render(page, QSize(max(1, int(size.width()*scale)), max(1, int(size.height()*scale))))
            output = QBuffer(); output.open(QIODevice.OpenModeFlag.WriteOnly)
            if image.isNull() or not image.save(output, 'PNG'): raise ValueError('PDF page rendering failed.')
            result.append(bytes(output.data()))
    finally:
        doc.close(); buffer.close()
    return result

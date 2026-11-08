"""Build packaged vector branding and raster fallbacks. Requires PySide6 and Pillow."""
import os
from pathlib import Path
import xml.etree.ElementTree as ET
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QImage, QPainter, QPainterPath, QFontDatabase, QRawFont
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'agentnik'/'assets'
ACCENT = '#d63b4b'


def path_data(path):
    parts=[]; i=0
    while i < path.elementCount():
        e=path.elementAt(i)
        if e.isMoveTo(): parts.append(f'M{e.x:g},{e.y:g}')
        elif e.isLineTo(): parts.append(f'L{e.x:g},{e.y:g}')
        elif e.isCurveTo():
            b,c=path.elementAt(i+1),path.elementAt(i+2)
            parts.append(f'C{e.x:g},{e.y:g} {b.x:g},{b.y:g} {c.x:g},{c.y:g}')
            i+=2
        i+=1
    return ' '.join(parts)


def render(svg, png, width=None, height=None):
    renderer=QSvgRenderer(str(svg))
    if not renderer.isValid(): raise ValueError(f'Invalid SVG: {svg}')
    size=renderer.defaultSize()
    image=QImage(width or size.width(),height or size.height(),QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter=QPainter(image)
    renderer.render(painter,QRectF(0,0,image.width(),image.height()))
    painter.end()
    if not image.save(str(png)): raise RuntimeError(f'Cannot write {png}')


def build():
    OUT.mkdir(exist_ok=True)
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    robot=ET.parse(ROOT/'assets/robot.svg').getroot()
    # Cropping/tracing can leave empty color regions. Qt warns on every d="".
    for parent in robot.iter():
        for child in list(parent):
            if child.tag == '{http://www.w3.org/2000/svg}path' and not child.get('d','').strip():
                parent.remove(child)
    # Use the robot geometry and red palette from the reusable icon source.
    content=''.join(ET.tostring(child,encoding='unicode') for child in robot if not child.tag.endswith('title'))
    icon=OUT/'agentnik-icon.svg'
    icon.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="453" height="438" viewBox="45 255 453 438"><title>Agentnik robot icon</title>{content}</svg>\n',encoding='utf-8')
    render(icon,icon.with_suffix('.png'),256,256)
    Image.open(icon.with_suffix('.png')).save(icon.with_suffix('.ico'),sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    # The offscreen Windows plugin does not discover system fonts automatically.
    font_path=Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/'seguibl.ttf'
    if font_path.exists(): QFontDatabase.addApplicationFont(str(font_path))
    font=QFont('Segoe UI'); font.setPixelSize(220); font.setWeight(QFont.Weight.Black)
    if not all(QRawFont.fromFont(font).glyphIndexesForString('agentnik')):
        raise RuntimeError('Install Segoe UI or configure an available font before rebuilding branding.')
    first=QPainterPath(); first.addText(0,0,font,'agent')
    last=QPainterPath(); last.addText(0,0,font,'nik')
    bounds=first.boundingRect(); gap=5
    last.translate(bounds.right()-last.boundingRect().left()+gap,0)
    total=first.united(last).boundingRect()
    width=int(480+total.width()+20)
    for variant,ink in [('light','#101b2e'),('dark','#f3f4f7')]:
        svg=OUT/f'agentnik-{variant}.svg'
        svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="438" viewBox="0 0 {width} 438"><title>Agentnik {variant} logo</title><g transform="translate(-45,-255)">{content}</g><g transform="translate({480-total.left():g},270)"><path fill="{ink}" d="{path_data(first)}"/><path fill="{ACCENT}" d="{path_data(last)}"/></g></svg>\n',encoding='utf-8')
        render(svg,svg.with_suffix('.png'))


if __name__=='__main__':
    app=QApplication([])
    build()

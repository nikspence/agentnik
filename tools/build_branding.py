"""Build packaged branding from the supplied transparent PNG artwork. Requires Pillow."""
import base64
import io
from pathlib import Path
import shutil
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'agentnik'/'assets'


def svg_image(data, width, height, title):
    """Embed the approved raster artwork without changing its appearance."""
    encoded=base64.b64encode(data).decode('ascii')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><title>{title}</title>'
            f'<image width="{width}" height="{height}" href="data:image/png;base64,{encoded}"/></svg>\n')


def extract_icon(logo):
    """Find the transparent gap between the robot and the wordmark, then pad to square."""
    image=logo.convert('RGBA');width,height=image.size
    alpha=image.getchannel('A').point(lambda value:255 if value>16 else 0)
    start=int(width*.20);end=int(width*.42);run=None;gap=None
    for x in range(start,end):
        blank=alpha.crop((x,0,x+1,height)).getbbox() is None
        if blank and run is None:run=x
        elif not blank and run is not None:
            if x-run>=max(4,width//300):gap=(run,x);break
            run=None
    if gap is None:raise ValueError('Could not find a transparent gap between the icon and wordmark')
    limit=(gap[0]+gap[1])//2
    icon=image.crop((0,0,limit,height));box=icon.getchannel('A').getbbox()
    if box is None:raise ValueError('Logo contains no visible robot icon')
    icon=icon.crop(box);margin=max(4,round(max(icon.size)*.04));side=max(icon.size)+2*margin
    result=Image.new('RGBA',(side,side),(0,0,0,0))
    result.alpha_composite(icon,((side-icon.width)//2,(side-icon.height)//2))
    return result


def png_bytes(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def build():
    OUT.mkdir(exist_ok=True)
    source_images={}
    for variant in ('light','dark'):
        source=ROOT/'assets'/f'agentnik-{variant}-source.png'
        with Image.open(source) as image:
            image.load()
            if image.mode!='RGBA' or image.getchannel('A').getextrema()[0]!=0:raise ValueError(f'{source.name} must have a transparent background')
            source_images[variant]=image.copy()
        data=source.read_bytes()
        shutil.copyfile(source,OUT/f'agentnik-{variant}.png')
        (OUT/f'agentnik-{variant}.svg').write_text(svg_image(data,*source_images[variant].size,f'Agentnik {variant} logo'),encoding='utf-8')
    icon=extract_icon(source_images['light']);data=png_bytes(icon)
    (OUT/'agentnik-icon.svg').write_text(svg_image(data,*icon.size,'Agentnik robot icon'),encoding='utf-8')
    (ROOT/'assets'/'robot.svg').write_text(svg_image(data,*icon.size,'Agentnik robot icon'),encoding='utf-8')
    icon_256=icon.resize((256,256),Image.Resampling.LANCZOS)
    icon_256.save(OUT/'agentnik-icon.png')
    icon_256.save(OUT/'agentnik-icon.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])


if __name__=='__main__':build()

"""Bounded, non-retrying client for OpenRouter-compatible Image API endpoints."""
import base64
import binascii
import json
import math
from urllib.parse import urlsplit

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImageReader
from . import core

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 24 * 1024 * 1024
MAX_REFERENCE_IMAGES = 4
MAX_PIXELS = 50_000_000
FORMATS = {'png': ('image/png', '.png'), 'jpeg': ('image/jpeg', '.jpg'), 'jpg': ('image/jpeg', '.jpg'), 'webp': ('image/webp', '.webp')}


class ImageRequestError(ValueError):
    """Image request failed; the message deliberately excludes provider data."""


class ImageRequestUncertain(ImageRequestError):
    """Submission may have reached the server; never replay automatically."""


def image_endpoint(connection, override=''):
    base=core.base_url(connection['url'])
    target=override.strip() if override else base+'/images'
    parsed=urlsplit(target);origin=urlsplit(base)
    if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or not parsed.path or parsed.hostname.lower()!=origin.hostname.lower()
        or parsed.scheme!=origin.scheme):
        raise ValueError('Image endpoint must use the selected connection host and scheme, without credentials or query parameters')
    try:parsed.port
    except ValueError:raise ValueError('Invalid image endpoint port') from None
    return target.rstrip('/')


def image_bytes(data):
    """Check bounded raster data and decode it before storage or transmission."""
    if not isinstance(data,bytes) or not data or len(data)>MAX_IMAGE_BYTES:raise ImageRequestError('Image data is empty or exceeds the image size limit')
    buf=QBuffer();buf.setData(QByteArray(data));buf.open(QIODevice.OpenModeFlag.ReadOnly)
    try:
        reader=QImageReader(buf);fmt=bytes(reader.format()).decode('ascii','ignore').lower()
        if fmt not in FORMATS or not reader.canRead():raise ImageRequestError('Only valid PNG, JPEG, and WebP images are supported')
        size=reader.size()
        if not size.isValid() or size.width()*size.height()>MAX_PIXELS:raise ImageRequestError('Image dimensions exceed the supported limit')
        if reader.read().isNull():raise ImageRequestError('The image could not be decoded')
        return FORMATS[fmt]
    finally:buf.close()


def _read_json(connection,url,body=None,timeout=180,cancel=None,maximum=MAX_RESPONSE_BYTES):
    if cancel and cancel.is_set():raise InterruptedError('Image request cancelled before submission')
    request_connection=dict(connection,protocol='responses')
    try:
        with core.open_request(request_connection,url,body,timeout=timeout) as response:
            data=response.read(maximum+1)
    except core.EndpointError as exc:
        raise ImageRequestError('Image endpoint rejected the request (HTTP '+str(exc.status)+')') from None
    except (OSError,TimeoutError,ValueError) as exc:
        if body is not None:raise ImageRequestUncertain('Image request did not complete; it may have been submitted. Check the provider before retrying.') from None
        raise ImageRequestError('Image model listing failed') from None
    if cancel and cancel.is_set():raise InterruptedError('Image request cancelled; the provider may have completed it')
    if len(data)>maximum:raise ImageRequestError('Image response exceeds the response size limit')
    try:return json.loads(data)
    except (ValueError,UnicodeError,RecursionError):raise ImageRequestError('Image endpoint returned invalid JSON') from None


def list_models(connection,endpoint='',cancel=None):
    result=_read_json(connection,image_endpoint(connection,endpoint)+'/models',cancel=cancel,timeout=30,maximum=4_000_000)
    data=result.get('data') if isinstance(result,dict) else None
    if not isinstance(data,list):raise ImageRequestError('Image endpoint returned an invalid model list')
    return sorted({entry['id'] for entry in data if isinstance(entry,dict) and isinstance(entry.get('id'),str) and 0<len(entry['id'])<=512})[:2000]


def generate(connection,model,prompt,references=(),endpoint='',cancel=None,aspect_ratio='',background=''):
    if not isinstance(model,str) or not model.strip() or len(model)>512:raise ValueError('Choose an image model')
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>16000:raise ValueError('Enter an image prompt of at most 16,000 characters')
    if not isinstance(references,(list,tuple)) or len(references)>MAX_REFERENCE_IMAGES:raise ValueError('Select up to four reference images')
    body={'model':model.strip(),'prompt':prompt.strip(),'n':1,'response_format':'b64_json'}
    if references:
        body['input_references']=[]
        for data in references:
            mime,_=image_bytes(data)
            body['input_references'].append({'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(data).decode('ascii')}})
    if aspect_ratio:
        if aspect_ratio not in ('1:1','16:9','9:16','4:3','3:4','3:2','2:3'):raise ValueError('Invalid aspect ratio')
        body['aspect_ratio']=aspect_ratio
    if background:
        if background not in ('transparent','opaque','auto'):raise ValueError('Invalid background')
        body['background']=background
    result=_read_json(connection,image_endpoint(connection,endpoint),body,cancel=cancel)
    data=result.get('data') if isinstance(result,dict) else None
    if not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],dict):raise ImageRequestError('Image endpoint returned an invalid image result')
    encoded=data[0].get('b64_json')
    if not isinstance(encoded,str) or len(encoded)>4*((MAX_IMAGE_BYTES+2)//3):raise ImageRequestError('Image endpoint returned invalid image data')
    try:image=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):raise ImageRequestError('Image endpoint returned invalid image data') from None
    mime,suffix=image_bytes(image)
    reported=data[0].get('media_type')
    if reported is not None and reported!=mime:raise ImageRequestError('Image content does not match the reported format')
    usage=result.get('usage',{});cost=usage.get('cost') if isinstance(usage,dict) else None
    if type(cost) not in (int,float) or not math.isfinite(cost) or cost<0:cost=None
    return {'data':image,'mime':mime,'suffix':suffix,'cost':cost}

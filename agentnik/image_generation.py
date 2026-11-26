"""Bounded, non-retrying client for OpenRouter-compatible Image API endpoints."""
import base64
import binascii
import json
import math
import re

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImageReader
from . import core
from .image_settings import image_endpoint

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 24 * 1024 * 1024
MAX_REFERENCE_IMAGES = 4
MAX_PIXELS = 50_000_000
FORMATS = {'png': ('image/png', '.png'), 'jpeg': ('image/jpeg', '.jpg'), 'jpg': ('image/jpeg', '.jpg'), 'webp': ('image/webp', '.webp')}


class ImageRequestError(ValueError):
    """Image request failed with bounded, allowlisted diagnostics."""


class ImageRequestUncertain(ImageRequestError):
    """Submission may have reached the server; never replay automatically."""


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


def provider_error_details(payload):
    """Return only recognized structured fields or fixed hints, never raw provider text."""
    if not isinstance(payload,dict):return ''
    error=payload.get('error')
    if not isinstance(error,dict):return ''
    parts=[]
    codes={'invalid_request_error','invalid_request','invalid_value','unsupported_parameter','model_not_found','content_policy_violation','invalid_image','rate_limit_exceeded','insufficient_quota'}
    code=error.get('code');param=error.get('param')
    if isinstance(code,str) and code in codes:parts.append('code='+code)
    allowed={'aspect_ratio','background','input_references','model','prompt','size','n','response_format','output_format','resolution'}
    if isinstance(param,str) and param in allowed:parts.append('parameter='+param)
    message=error.get('message')
    if isinstance(message,str):
        # OpenRouter reports this route-selection error with model and provider data;
        # retain only the fixed reason and recognized parameter names.
        if re.search(r'no provider for .{1,300} supports the requested parameter',message,re.I):
            # The message may also mention supported parameters or echo request data.
            # Do not infer which individual fields failed from incidental mentions.
            parts.append('No available provider supports the requested parameter combination')
        elif re.search(r'(?:background.{0,80}transparent|transparent.{0,80}background).{0,80}(?:not supported|unsupported)',message,re.I):
            parts.append('Provider reports transparent background is unsupported')
    return '; '.join(parts)


def request_options(aspect_ratio,background,reference_count):
    aspect=aspect_ratio if isinstance(aspect_ratio,str) and aspect_ratio in ('','1:1','16:9','9:16','4:3','3:4','3:2','2:3') else 'invalid'
    back=background if isinstance(background,str) and background in ('','transparent','opaque','auto') else 'invalid'
    count=str(reference_count) if type(reference_count) is int and 0<=reference_count<=MAX_REFERENCE_IMAGES else 'invalid'
    return 'Request options: aspect_ratio='+(aspect or 'auto')+', background='+(back or 'auto')+', reference_count='+count+'.'


def _read_json(connection,url,body=None,timeout=180,cancel=None,maximum=MAX_RESPONSE_BYTES):
    if cancel and cancel.is_set():raise InterruptedError('Image request cancelled before submission')
    request_connection=dict(connection,protocol='responses')
    try:
        with core.open_request(request_connection,url,body,timeout=timeout) as response:
            data=response.read(maximum+1)
    except core.EndpointError as exc:
        if body is not None and (exc.status==408 or exc.status>=500):raise ImageRequestUncertain('Image request failed after submission; check the provider before retrying.') from None
        detail=provider_error_details(exc.payload)
        raise ImageRequestError('Image endpoint rejected the request (HTTP '+str(exc.status)+')'+(': '+detail if detail else '')) from None
    except (OSError,TimeoutError,ValueError) as exc:
        if body is not None:raise ImageRequestUncertain('Image request did not complete; it may have been submitted. Check the provider before retrying.') from None
        raise ImageRequestError('Image model listing failed') from None
    if cancel and cancel.is_set():raise InterruptedError('Image request cancelled; the provider may have completed it')
    if len(data)>maximum:
        if body is not None:raise ImageRequestUncertain('Image response exceeded the size limit after submission; check the provider before retrying.')
        raise ImageRequestError('Image response exceeds the response size limit')
    try:return json.loads(data)
    except (ValueError,UnicodeError,RecursionError):
        if body is not None:raise ImageRequestUncertain('Image endpoint returned invalid JSON after submission; check the provider before retrying.') from None
        raise ImageRequestError('Image endpoint returned invalid JSON') from None


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
    try:result=_read_json(connection,image_endpoint(connection,endpoint),body,cancel=cancel)
    except ImageRequestError as exc:
        raise type(exc)(str(exc)+' '+request_options(aspect_ratio,background,len(references))) from None
    data=result.get('data') if isinstance(result,dict) else None
    if not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],dict):raise ImageRequestUncertain('Image endpoint returned an invalid image result after submission; check the provider before retrying')
    encoded=data[0].get('b64_json')
    if not isinstance(encoded,str) or len(encoded)>4*((MAX_IMAGE_BYTES+2)//3):raise ImageRequestUncertain('Image endpoint returned invalid image data after submission; check the provider before retrying')
    try:image=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):raise ImageRequestUncertain('Image endpoint returned invalid image data after submission; check the provider before retrying') from None
    try:mime,suffix=image_bytes(image)
    except ImageRequestError:raise ImageRequestUncertain('Image endpoint returned an unreadable image after submission; check the provider before retrying') from None
    reported=data[0].get('media_type')
    if reported is not None and reported!=mime:raise ImageRequestUncertain('Image content does not match the reported format; check the provider before retrying')
    usage=result.get('usage',{});cost=usage.get('cost') if isinstance(usage,dict) else None
    if type(cost) not in (int,float) or not math.isfinite(cost) or cost<0:cost=None
    return {'data':image,'mime':mime,'suffix':suffix,'cost':cost}

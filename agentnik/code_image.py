"""Project-scoped, conflict-checked image generation for Code."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from PySide6.QtCore import QByteArray,QBuffer,QIODevice
from PySide6.QtGui import QImage
from . import image_generation


def references(files, attached, raw):
    try:items=json.loads(raw)
    except (ValueError,TypeError):raise ValueError('reference_paths must be a JSON array of project paths or attachment:N identifiers') from None
    if not isinstance(items,list) or len(items)>image_generation.MAX_REFERENCE_IMAGES or any(not isinstance(x,str) for x in items):raise ValueError('Select at most four image references')
    result=[];project_paths=[]
    for item in items:
        if item.startswith('attachment:'):
            number=item.removeprefix('attachment:')
            if not number.isdecimal() or not 1<=int(number)<=len(attached):raise ValueError('Invalid attachment reference')
            path=Path(attached[int(number)-1])
        else:
            path=files.path(item);project_paths.append(os.path.normcase(str(path)))
        if not path.is_file():raise ValueError('Reference image is unavailable')
        with path.open('rb') as source:data=source.read(image_generation.MAX_IMAGE_BYTES+1)
        image_generation.image_bytes(data);result.append(data)
    return result,project_paths


def prepare(files,path,project_paths):
    target=files.path(path)
    if target.suffix.lower() not in ('.png','.jpg','.jpeg','.webp') or not target.parent.is_dir():raise ValueError('Choose a PNG, JPEG, or WebP project path in an existing folder')
    if not target.exists():return None
    if not target.is_file() or os.path.normcase(str(target)) not in project_paths:raise ValueError('To replace an existing image, include it in reference_paths')
    with target.open('rb') as source:data=source.read(image_generation.MAX_IMAGE_BYTES+1)
    image_generation.image_bytes(data)
    return hashlib.sha256(data).hexdigest()


def convert(data,suffix):
    target={'.png':'PNG','.jpg':'JPEG','.jpeg':'JPEG','.webp':'WEBP'}[suffix.lower()]
    image=QImage.fromData(data)
    if image.isNull():raise ValueError('Generated image could not be decoded')
    if target=='JPEG' and image.hasAlphaChannel():raise ValueError('Use a PNG or WebP destination to preserve transparency')
    value=QByteArray();buffer=QBuffer(value);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        if not image.save(buffer,target):raise ValueError('Cannot encode the generated image in the requested format')
    finally:buffer.close()
    result=bytes(value);image_generation.image_bytes(result);return result


def _matches(target,base):
    if not target.is_file():return False
    with target.open('rb') as stream:data=stream.read(image_generation.MAX_IMAGE_BYTES+1)
    return len(data)<=image_generation.MAX_IMAGE_BYTES and hashlib.sha256(data).hexdigest()==base


def publish(files,path,base,data,check):
    from .code_agent import _EDIT_LOCK
    with _EDIT_LOCK:
        target=files.path(path);check()
        if base is None:
            if target.exists():raise ValueError('Image destination appeared during generation')
            mode=None
        else:
            if not _matches(target,base):raise ValueError('Image changed during generation')
            mode=stat.S_IMODE(target.stat().st_mode)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.agentnik-image-',delete=False) as stream:
                temporary=Path(stream.name);stream.write(data);stream.flush();os.fsync(stream.fileno())
            if mode is not None:os.chmod(temporary,mode)
            target=files.path(path);check()
            if base is not None:
                if not _matches(target,base):raise ValueError('Image changed during generation')
                os.replace(temporary,target)
            else:os.link(temporary,target)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)

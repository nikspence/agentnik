"""Persistent image tool settings without credentials."""
from urllib.parse import urlsplit

from . import core

DEFAULT = {'enabled':False,'connection':'','model':'','endpoint':''}


def validate_image_settings(value):
    if value is None:return dict(DEFAULT)
    if not isinstance(value,dict) or set(value)!=set(DEFAULT):raise ValueError('Invalid image generation settings')
    if type(value['enabled']) is not bool:raise ValueError('Invalid image generation setting')
    for name,limit in (('connection',512),('model',512),('endpoint',2048)):
        if not isinstance(value[name],str) or len(value[name])>limit:raise ValueError('Invalid image generation setting')
    return dict(value)


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

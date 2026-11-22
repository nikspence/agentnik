"""Persistent image tool settings without credentials."""
DEFAULT = {'enabled':False,'connection':'','model':'','endpoint':''}


def validate_image_settings(value):
    if value is None:return dict(DEFAULT)
    if not isinstance(value,dict) or set(value)!=set(DEFAULT):raise ValueError('Invalid image generation settings')
    if type(value['enabled']) is not bool:raise ValueError('Invalid image generation setting')
    for name,limit in (('connection',512),('model',512),('endpoint',2048)):
        if not isinstance(value[name],str) or len(value[name])>limit:raise ValueError('Invalid image generation setting')
    return dict(value)

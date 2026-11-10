"""Validated per-run budgets for coding and managed research."""

# key: (default, minimum, maximum)
FIELDS = {
    'rounds': (8, 1, 64),
    'requests': (9, 1, 128),
    'calls': (16, 1, 128),
    'turn_seconds': (900, 10, 3600),
    'model_seconds': (300, 10, 3600),
    'context_bytes': (100000, 4096, 1000000),
}


def coding_limits(value=None):
    if value is None:
        return {key: limits[0] for key, limits in FIELDS.items()}
    if not isinstance(value, dict) or set(value) not in (set(FIELDS),set(FIELDS)-{'model_seconds'}):
        raise ValueError('Invalid coding limits')
    value=dict(value)
    value.setdefault('model_seconds',FIELDS['model_seconds'][0])
    for key, (_, minimum, maximum) in FIELDS.items():
        if type(value[key]) is not int or not minimum <= value[key] <= maximum:
            raise ValueError('Invalid coding limit: '+key)
    return dict(value)

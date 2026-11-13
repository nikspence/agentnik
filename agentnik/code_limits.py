"""Validated per-run budgets for coding and managed research."""

# key: (default, minimum, maximum)
FIELDS = {
    'rounds': (48, 1, 64),
    'requests': (50, 1, 128),
    'calls': (96, 1, 128),
    'turn_seconds': (3600, 10, 3600),
    'model_seconds': (300, 10, 3600),
    'context_bytes': (1000000, 4096, 8000000),
}

FULL_TEXT_BYTES=128_000
PATCH_FILE_BYTES=10_000_000
RANGE_TEXT_BYTES=64_000
PATCH_TEXT_BYTES=64_000


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

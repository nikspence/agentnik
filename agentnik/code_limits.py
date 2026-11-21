"""Validated per-run budgets for coding and managed research."""

# key: (default, minimum, maximum)
FIELDS = {
    'rounds': (48, 1, 128),
    'requests': (50, 1, 256),
    'calls': (96, 1, 256),
    'turn_seconds': (3600, 10, 7200),
    'model_seconds': (300, 10, 7200),
    'context_bytes': (2000000, 4096, 16000000),
}

FULL_TEXT_BYTES=128_000
PATCH_FILE_BYTES=10_000_000
RANGE_TEXT_BYTES=64_000
PATCH_TEXT_BYTES=64_000

# Zero means unlimited. Goal time is active running time, excluding pauses.
GOAL_FIELDS={'steps':(0,0,2000000),'seconds':(0,0,63072000)}


def goal_limits(value=None):
    if value is None:return {key:item[0] for key,item in GOAL_FIELDS.items()}
    if not isinstance(value,dict) or set(value)!=set(GOAL_FIELDS):raise ValueError('Invalid goal limits')
    for key,(_,low,high) in GOAL_FIELDS.items():
        if type(value[key]) is not int or not low<=value[key]<=high:raise ValueError('Invalid goal limit: '+key)
    return dict(value)


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

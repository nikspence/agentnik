"""Bounded, process-local cache for successful search results."""
import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict

_TTL = 1800
_MAX_ENTRIES = 100
_MAX_BYTES = 2_000_000
_lock = threading.Lock()
_entries = OrderedDict()

def key(*parts):
    data = json.dumps(parts, sort_keys=True, ensure_ascii=True, default=str).encode('utf-8')
    return hashlib.sha256(data).digest()

def get(cache_key):
    with _lock:
        item = _entries.get(cache_key)
        if item is None:
            return None
        if time.monotonic() - item[0] >= _TTL:
            del _entries[cache_key]
            return None
        _entries.move_to_end(cache_key)
        return copy.deepcopy(item[1])

def put(cache_key, value):
    try:
        size = len(json.dumps(value, default=lambda o: vars(o), ensure_ascii=True).encode('utf-8'))
    except (TypeError, ValueError, RecursionError):
        return
    if size > _MAX_BYTES:
        return
    with _lock:
        _entries[cache_key] = (time.monotonic(), copy.deepcopy(value), size)
        _entries.move_to_end(cache_key)
        while len(_entries) > _MAX_ENTRIES or sum(item[2] for item in _entries.values()) > _MAX_BYTES:
            _entries.popitem(last=False)

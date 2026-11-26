"""Redact streamed response snapshots before exposing them to a client."""

import re


def visible_prefix(text, secrets, limit=32000):
    keys = sorted({key for key in secrets if key}, key=len, reverse=True)
    if not keys:
        return text[:limit]
    # Hold any suffix that a later chunk could complete into a secret.
    cutoff = len(text)
    for key in keys:
        for size in range(min(len(key) - 1, len(text)), 0, -1):
            if text.endswith(key[:size]):
                cutoff = min(cutoff, len(text) - size)
                break
    pattern = re.compile("|".join(map(re.escape, keys)))
    pieces = []
    start = 0
    for match in pattern.finditer(text):
        if match.start() >= cutoff:
            break
        pieces.extend((text[start:match.start()], "[redacted]"))
        start = match.end()
    pieces.append(text[start:cutoff])
    return "".join(pieces)[:limit]

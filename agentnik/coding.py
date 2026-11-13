"""Shared display sanitization for coding activity."""
import re


def plain(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]','',str(value))[:2048]

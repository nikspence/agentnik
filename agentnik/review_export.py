"""Prepare and write explicit, bounded review snapshot exports."""
import json
from pathlib import Path

from .independent_review import validate_review_history
from .track_drafting import contains_secrets


def prepare_review_export(snapshot, secrets=()):
    """Return the exact JSON to preview; never include configured credentials."""
    record=validate_review_history([snapshot])[0]
    payload={'format':'agentnik-review-snapshot','version':1,'snapshot':record}
    if contains_secrets(payload,secrets):raise ValueError('The review snapshot contains a configured credential and cannot be exported.')
    return json.dumps(payload,ensure_ascii=False,indent=2)+'\n'


def write_new_review_export(path, content):
    """Create a new UTF-8 file without replacing an existing destination."""
    if not isinstance(content,str) or not content:raise ValueError('Invalid review export')
    with Path(path).open('x',encoding='utf-8',newline='\n') as output:output.write(content)

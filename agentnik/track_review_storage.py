"""Read and validate legacy project-local review history."""

from .independent_review import validate_review_history
from .tracks import IDENTIFIER, ROOT, parse_json
from .code_limits import FULL_TEXT_BYTES

SIDECAR = 'reviews.json'
MAX_SNAPSHOTS = 10


def sidecar_path(track_id):
    if not isinstance(track_id, str) or not IDENTIFIER.fullmatch(track_id):
        raise ValueError('Invalid track id')
    return ROOT+'/'+track_id+'/'+SIDECAR


def validate_sidecar(value, track_id):
    sidecar_path(track_id)
    if not isinstance(value, dict) or set(value) != {'version', 'track_id', 'snapshots'} or type(value['version']) is not int or value['version'] != 1 or value['track_id'] != track_id:
        raise ValueError('Invalid or unsupported track review history')
    snapshots=validate_review_history(value['snapshots'])
    if len(snapshots)>MAX_SNAPSHOTS:raise ValueError('Track review history is full')
    for snapshot in snapshots:
        if snapshot['track_id'] not in (None, track_id):raise ValueError('Review snapshot belongs to another track')
        if any(not review.get('track_context') or review['track_context']['id'] != track_id for review in snapshot['reviews']):
            raise ValueError('Every review must identify this track context')
    return {'version':1,'track_id':track_id,'snapshots':snapshots}


def read_sidecar(files, track_id):
    """Read a sidecar without creating or rewriting files."""
    path=sidecar_path(track_id);target=files.path(path)
    if not target.exists():return {'version':1,'track_id':track_id,'snapshots':[]}
    return validate_sidecar(parse_json(files.read(path,remember=False,max_bytes=FULL_TEXT_BYTES)),track_id)

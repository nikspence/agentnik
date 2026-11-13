"""Approval-bound project-local review history; no implicit UI or model calls."""
import copy
import json
import re

from .independent_review import validate_review_history
from .track_drafting import contains_secrets
from .track_execution import prepare_track
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


def prepare_append(files, track_id, snapshot, secrets=()):
    """Prepare one full diff; files and sidecar remain unchanged."""
    track=prepare_track(files,track_id,secrets)
    path=sidecar_path(track_id)
    current=validate_sidecar(parse_json(files.read(path,remember=True,max_bytes=FULL_TEXT_BYTES)),track_id) if files.path(path).exists() else {'version':1,'track_id':track_id,'snapshots':[]}
    candidate=validate_sidecar({'version':1,'track_id':track_id,'snapshots':current['snapshots']+[copy.deepcopy(snapshot)]},track_id)
    if contains_secrets(candidate,secrets):raise ValueError('Review history contains a configured credential')
    content=json.dumps(candidate,ensure_ascii=False,indent=2)+'\n'
    if len(content.encode('utf-8'))>FULL_TEXT_BYTES:raise ValueError('Track review history exceeds the file size limit')
    proposal=files.proposal(path,content)
    return {'track_id':track_id,'track_digest':track['digest'],'proposal':proposal}


def prepare_remove(files, track_id, snapshot_id, secrets=()):
    """Prepare a reviewed removal while keeping the sidecar and other records."""
    if not isinstance(snapshot_id,str) or not re.fullmatch('[0-9a-f]{32}',snapshot_id):raise ValueError('Invalid review snapshot id')
    track=prepare_track(files,track_id,secrets);path=sidecar_path(track_id)
    current=validate_sidecar(parse_json(files.read(path,remember=True,max_bytes=FULL_TEXT_BYTES)),track_id)
    if not any(item['id']==snapshot_id for item in current['snapshots']):raise ValueError('Review snapshot is unavailable')
    candidate=validate_sidecar({'version':1,'track_id':track_id,'snapshots':[item for item in current['snapshots'] if item['id']!=snapshot_id]},track_id)
    if contains_secrets(candidate,secrets):raise ValueError('Review history contains a configured credential')
    content=json.dumps(candidate,ensure_ascii=False,indent=2)+'\n'
    proposal=files.proposal(path,content)
    return {'track_id':track_id,'track_digest':track['digest'],'proposal':proposal}


def apply_append(files, prepared, approve, secrets=()):
    """Request approval and apply an exact sidecar diff if inputs stay current."""
    if not isinstance(prepared,dict) or set(prepared)!={'track_id','track_digest','proposal'}:raise ValueError('Invalid track review proposal')
    ident=prepared['track_id'];proposal=prepared['proposal'];path=sidecar_path(ident)
    if not isinstance(proposal,dict) or proposal.get('path')!=path or proposal.get('cwd')!=str(files.root):raise ValueError('Invalid track review proposal')
    data=validate_sidecar(parse_json(proposal['content']),ident)
    if contains_secrets(data,secrets):raise ValueError('Review history contains a configured credential')
    if files.proposal(path,proposal['content'])!=proposal:raise ValueError('Track review proposal changed; prepare it again')
    def check_track():
        if prepare_track(files,ident,secrets)['digest']!=prepared['track_digest']:
            raise ValueError('Track changed after review; inspect and start again')
    check_track()
    if not approve(copy.deepcopy(proposal)):return {'status':'rejected','path':path}
    files.apply(proposal,check_track)
    return {'status':'completed','path':path}

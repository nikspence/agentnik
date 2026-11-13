"""Prepare selected tracks and validate run-local, non-authoritative progress."""
import copy
import hashlib
import json
import unicodedata
from .tracks import ROOT,MAX_DOCUMENT_BYTES,IDENTIFIER,parse_json,read_project_context,validate_track
from .task_plan import validate_plan,STATUSES
from .track_drafting import contains_secrets

MAX_TRACK_CONTEXT_BYTES=60_000


def prepare_track(files,ident,secrets=(),context_limit=1_000_000):
    if not isinstance(ident,str) or not IDENTIFIER.fullmatch(ident):raise ValueError('Invalid track id')
    base=ROOT+'/'+ident+'/'
    raw={name:files.read(base+name,remember=False,max_bytes=MAX_DOCUMENT_BYTES) for name in ('track.json','spec.md','plan.md')}
    track=validate_track(parse_json(raw['track.json']),ident)['track'];context=read_project_context(files)
    source_hashes={name:hashlib.sha256(value.encode('utf-8')).hexdigest() for name,value in raw.items()}
    source_hashes['context.md']=hashlib.sha256(context.encode('utf-8')).hexdigest() if context is not None else None
    source_digest=hashlib.sha256(json.dumps(source_hashes,sort_keys=True).encode()).hexdigest()
    data={'track':track,'spec':raw['spec.md'],'plan':raw['plan.md'],'project_context':context,'source_hashes':source_hashes}
    if contains_secrets(data,secrets):raise ValueError('The track contains a configured credential; remove it before sending')
    encoded=json.dumps(data,ensure_ascii=False,indent=2)
    if len(encoded.encode('utf-8'))>min(MAX_TRACK_CONTEXT_BYTES,context_limit):raise ValueError('Selected track context exceeds the run budget or 60,000-byte limit')
    return {'id':ident,'digest':source_digest,'context':encoded,'tasks':[{'id':t['id'],'step':t['step'],'status':t['status']} for t in track['tasks']],'explanation':track['explanation']}


def validate_runtime_track(track):
    if not isinstance(track,dict) or set(track)!={'id','digest','context','tasks','explanation'}:raise ValueError('Invalid selected track')
    if not isinstance(track['id'],str) or not IDENTIFIER.fullmatch(track['id']):raise ValueError('Invalid selected track id')
    if not isinstance(track['digest'],str) or not __import__('re').fullmatch('[0-9a-f]{64}',track['digest']):raise ValueError('Invalid selected track digest')
    if not isinstance(track['context'],str) or not track['context'] or len(track['context'].encode('utf-8'))>MAX_TRACK_CONTEXT_BYTES:raise ValueError('Invalid selected track context')
    tasks=track['tasks']
    if not isinstance(tasks,list) or not 1<=len(tasks)<=20:raise ValueError('Invalid selected track tasks')
    seen=set();steps=[]
    for task in tasks:
        if not isinstance(task,dict) or set(task)!={'id','step','status'}:raise ValueError('Invalid selected track task')
        ident=task['id']
        if not isinstance(ident,str) or not IDENTIFIER.fullmatch(ident) or ident in seen:raise ValueError('Invalid selected track task id')
        seen.add(ident);steps.append({'step':task['step'],'status':task['status']})
    validate_plan({'explanation':track['explanation'],'steps':steps})
    return copy.deepcopy(track)


def initial_progress(track):
    track=validate_runtime_track(track)
    return {'track_id':track['id'],'source_digest':track['digest'],'tasks':[{'id':task['id'],'status':task['status'],'detail':''} for task in track['tasks']]}


def validate_progress(value):
    if not isinstance(value,dict) or set(value)!={'track_id','source_digest','tasks'}:raise ValueError('Invalid track progress')
    ident=value['track_id'];source=value['source_digest'];tasks=value['tasks']
    if not isinstance(ident,str) or not IDENTIFIER.fullmatch(ident) or not isinstance(source,str) or not __import__('re').fullmatch('[0-9a-f]{64}',source):raise ValueError('Invalid track progress identity')
    if not isinstance(tasks,list) or not 1<=len(tasks)<=20:raise ValueError('Invalid track progress tasks')
    seen=set();active=0
    for task in tasks:
        if not isinstance(task,dict) or set(task)!={'id','status','detail'}:raise ValueError('Invalid track progress task')
        task_id=task['id'];status=task['status'];detail=task['detail']
        if not isinstance(task_id,str) or not IDENTIFIER.fullmatch(task_id) or task_id in seen or not isinstance(status,str) or status not in STATUSES:raise ValueError('Invalid track progress task')
        if not isinstance(detail,str) or len(detail)>500 or any(unicodedata.category(c)=='Cc' or unicodedata.bidirectional(c) in ('LRE','RLE','LRO','RLO','PDF','LRI','RLI','FSI','PDI') for c in detail):raise ValueError('Invalid track progress detail')
        seen.add(task_id);active+=status=='in_progress'
    if active>1:raise ValueError('Only one task may be in progress')
    return copy.deepcopy(value)


def update_progress(progress,updates):
    progress=validate_progress(progress)
    if not isinstance(updates,list) or not 1<=len(updates)<=20:raise ValueError('Supply 1–20 task updates')
    by_id={task['id']:task for task in progress['tasks']};seen=set()
    for update in updates:
        if not isinstance(update,dict) or set(update)!={'id','status','detail'} or not isinstance(update['id'],str) or update['id'] not in by_id or update['id'] in seen:raise ValueError('Unknown, duplicate, or invalid track task id')
        seen.add(update['id']);by_id[update['id']].update(update)
    return validate_progress(progress)


def projected_plan(track,progress):
    track=validate_runtime_track(track);progress=validate_progress(progress)
    if track['id']!=progress['track_id'] or track['digest']!=progress['source_digest'] or [t['id'] for t in track['tasks']]!=[t['id'] for t in progress['tasks']]:raise ValueError('Track progress does not match selected track')
    return validate_plan({'explanation':track['explanation'],'steps':[{'step':task['step'],'status':reported['status']} for task,reported in zip(track['tasks'],progress['tasks'])]})

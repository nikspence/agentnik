"""Read-only v1 durable project track contract. Never writes project files."""
import copy
import json
import re
import unicodedata
from pathlib import Path
from .task_plan import validate_plan

ROOT='agentnik-plans/tracks'
MAX_TRACKS=100
MAX_DOCUMENT_BYTES=128_000
IDENTIFIER=re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
EVIDENCE_STATES={'passed','failed','unknown','not_run'}


def one_line(value,limit):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=limit and not any(unicodedata.category(c)=='Cc' or unicodedata.bidirectional(c) in ('LRE','RLE','LRO','RLO','PDF','LRI','RLI','FSI','PDI') for c in value)


def parse_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate JSON field')
            result[key]=value
        return result
    return json.loads(text,object_pairs_hook=pairs)


def validate_track(value, directory_id=None):
    if not isinstance(value,dict) or set(value)!={'version','id','title','explanation','tasks'}:raise ValueError('Unsupported track fields')
    if type(value['version']) is not int or value['version']!=1:raise ValueError('Unsupported track version')
    ident=value['id'];title=value['title'];tasks=value['tasks']
    if not isinstance(ident,str) or not IDENTIFIER.fullmatch(ident) or (directory_id is not None and ident!=directory_id):raise ValueError('Invalid or mismatched track id')
    if not one_line(title,160):raise ValueError('Invalid track title')
    if not isinstance(tasks,list) or not 1<=len(tasks)<=20:raise ValueError('Track requires 1–20 tasks')
    ids=set();steps=[]
    for task in tasks:
        if not isinstance(task,dict) or set(task)!={'id','phase','step','status','evidence'}:raise ValueError('Unsupported task fields')
        task_id=task['id'];phase=task['phase'];evidence=task['evidence']
        if not isinstance(task_id,str) or not IDENTIFIER.fullmatch(task_id) or task_id in ids:raise ValueError('Invalid or duplicate task id')
        ids.add(task_id)
        if not one_line(phase,120):raise ValueError('Invalid task phase')
        if not isinstance(evidence,list) or len(evidence)>8:raise ValueError('Invalid verification evidence')
        for item in evidence:
            if not isinstance(item,dict) or set(item)!={'status','detail'} or not isinstance(item['status'],str) or item['status'] not in EVIDENCE_STATES:raise ValueError('Invalid verification evidence')
            if not one_line(item['detail'],500):raise ValueError('Invalid evidence description')
        steps.append({'step':task['step'],'status':task['status']})
    projection=validate_plan({'explanation':value['explanation'],'steps':steps})
    return {'track':copy.deepcopy(value),'projection':projection,'task_ids':[task['id'] for task in tasks]}


def list_tracks(files,check=lambda:None):
    root=files.path(ROOT)
    if not root.exists():return {'tracks':[],'incomplete':False}
    if not root.is_dir():raise ValueError('Track directory is unavailable')
    tracks=[];incomplete=False;scanned=0
    with __import__('os').scandir(root) as entries:
        for entry in entries:
            check();scanned+=1
            if len(tracks)>=MAX_TRACKS or scanned>200:incomplete=True;break
            if not entry.is_dir(follow_symlinks=False):continue
            if not IDENTIFIER.fullmatch(entry.name):
                tracks.append({'id':entry.name[:64],'available':False,'reason':'Invalid track directory name'});continue
            try:
                files.path(ROOT+'/'+entry.name)
                raw=files.read(ROOT+'/'+entry.name+'/track.json',remember=False,max_bytes=MAX_DOCUMENT_BYTES)
                record=validate_track(parse_json(raw),entry.name)['track']
                tracks.append({'id':entry.name,'available':True,'title':record['title']})
            except (ValueError,OSError,UnicodeError,RecursionError):tracks.append({'id':entry.name,'available':False,'reason':'Track metadata is missing, invalid, or unsupported'})
    return {'tracks':sorted(tracks,key=lambda row:row['id']),'incomplete':incomplete}


def read_track(files,ident):
    if not isinstance(ident,str) or not IDENTIFIER.fullmatch(ident):raise ValueError('Invalid track id')
    base=ROOT+'/'+ident+'/'
    try:
        metadata=files.read(base+'track.json',remember=False,max_bytes=MAX_DOCUMENT_BYTES)
        result=validate_track(parse_json(metadata),ident)
        result['spec']=files.read(base+'spec.md',remember=False,max_bytes=MAX_DOCUMENT_BYTES)
        result['plan']=files.read(base+'plan.md',remember=False,max_bytes=MAX_DOCUMENT_BYTES)
    except (OSError,UnicodeError,RecursionError):raise ValueError('Track files are unavailable or not UTF-8') from None
    return result


def read_project_context(files):
    """Return optional project context without creating or changing project files."""
    relative='agentnik-plans/context.md';target=files.path(relative)
    if not target.exists():return None
    return files.read(relative,remember=False,max_bytes=MAX_DOCUMENT_BYTES)

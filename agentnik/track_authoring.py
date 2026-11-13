"""User-authored track drafts and individually reviewed new-file publication."""
import hashlib
import copy
import json
from .tracks import ROOT,MAX_DOCUMENT_BYTES,validate_track


def validate_draft(value):
    if not isinstance(value,dict) or set(value)!={'metadata','spec','plan','created_dirs','written'}:raise ValueError('Invalid track draft')
    track=validate_track(value['metadata'])['track'];ident=track['id']
    if len((json.dumps(track,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))>MAX_DOCUMENT_BYTES:raise ValueError('Track metadata exceeds 128,000 UTF-8 bytes')
    for key in ('spec','plan'):
        text=value[key]
        if not isinstance(text,str) or not text.strip() or '\x00' in text or len(text.encode('utf-8'))>MAX_DOCUMENT_BYTES:raise ValueError('Specification and plan must be nonempty UTF-8 text of at most 128,000 bytes')
    dirs=value['created_dirs'];written=value['written'];allowed_dirs={'agentnik-plans',ROOT,ROOT+'/'+ident};allowed_files={ROOT+'/'+ident+'/'+name for name in ('spec.md','plan.md','track.json')}
    if not isinstance(dirs,list) or len(dirs)>3 or any(not isinstance(d,str) or d not in allowed_dirs for d in dirs) or len(set(dirs))!=len(dirs):raise ValueError('Invalid draft publication state')
    if not isinstance(written,dict) or len(written)>3 or any(not isinstance(k,str) or k not in allowed_files or not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for k,v in written.items()):raise ValueError('Invalid draft publication state')
    return {'metadata':track,'spec':value['spec'],'plan':value['plan'],'created_dirs':list(dirs),'written':dict(written)}


def new_draft():
    return {'metadata':{'version':1,'id':'new_track','title':'New track','explanation':'','tasks':[{'id':'task_1','phase':'Planning','step':'Describe the first task','status':'pending','evidence':[]}]},'spec':'# Specification\n\n## Requirements\n\n## Acceptance criteria\n','plan':'# Plan\n\nDescribe the implementation phases.\n','created_dirs':[],'written':{}}


def draft_files(draft):
    draft=validate_draft(draft);base=ROOT+'/'+draft['metadata']['id']+'/'
    return [(base+'spec.md',draft['spec']),(base+'plan.md',draft['plan']),(base+'track.json',json.dumps(draft['metadata'],ensure_ascii=False,indent=2)+'\n')]


def publish(files,draft,approve,on_change=lambda draft:None):
    """Publish only new files after individual approval; retain partial progress.

    `approve` sees a fully formed ProjectFiles proposal and returns a bool.
    `on_change` persists the draft after each successful operation.
    """
    draft=validate_draft(draft);items=draft_files(draft);ident=draft['metadata']['id']
    directories=['agentnik-plans',ROOT,ROOT+'/'+ident];written=draft['written'];created=draft['created_dirs']
    track_path=files.path(directories[-1])
    if track_path.exists() and directories[-1] not in created:raise ValueError('Track directory already exists; choose a different track id')
    def check_written():
        for path,content in items:
            target=files.path(path);digest=hashlib.sha256(content.encode('utf-8')).hexdigest()
            if path in written:
                if written[path]!=digest:raise ValueError('Draft changed after a file was published; inspect the partial track before continuing')
                if not target.is_file() or hashlib.sha256(files.read(path,remember=False,max_bytes=MAX_DOCUMENT_BYTES).encode('utf-8')).hexdigest()!=digest:raise ValueError('A published file changed or disappeared; inspect the partial track before continuing')
            elif target.exists():raise ValueError('A target file already exists; no file will be overwritten')
    check_written()
    for path in directories:
        target=files.path(path)
        if target.exists():
            if not target.is_dir():raise ValueError('A required directory is unavailable')
            continue
        if path in created:raise ValueError('A previously created directory disappeared; inspect the partial track before continuing')
        proposal=files.directory_proposal(path)
        if not approve(copy.deepcopy(proposal)):return {'status':'rejected','draft':draft,'last_path':path}
        files.apply_operation(proposal,check_written);created.append(path);on_change(copy.deepcopy(draft))
    for path,content in items:
        if path in written:continue
        proposal=files.proposal(path,content)
        if proposal['base'] is not None:raise ValueError('A target file already exists; no file will be overwritten')
        if not approve(copy.deepcopy(proposal)):return {'status':'rejected','draft':draft,'last_path':path}
        files.apply(proposal,check_written);written[path]=hashlib.sha256(content.encode('utf-8')).hexdigest();on_change(copy.deepcopy(draft))
    check_written()
    return {'status':'completed','draft':draft,'last_path':items[-1][0]}

"""Prepare explicit, revision-bound track status edits without writing files."""
import json
from .track_execution import prepare_track,validate_progress
from .track_editing import load_edit,validate_edit
from .tracks import parse_json,validate_track


def _members(text,start):
    """Return JSON object value spans, retaining the original formatting."""
    decoder=json.JSONDecoder();i=start+1;result={}
    while True:
        while text[i].isspace():i+=1
        if text[i]=='}':return result
        key,i=decoder.raw_decode(text,i)
        while text[i].isspace():i+=1
        if text[i]!=':':raise ValueError('Invalid metadata')
        i+=1
        while text[i].isspace():i+=1
        begin=i;_,i=decoder.raw_decode(text,i);result[key]=(begin,i)
        while text[i].isspace():i+=1
        if text[i]=='}':return result
        if text[i]!=',':raise ValueError('Invalid metadata')
        i+=1


def _task_spans(text):
    start=_members(text,len(text)-len(text.lstrip()))['tasks'][0]+1;decoder=json.JSONDecoder();result=[];i=start
    while True:
        while text[i].isspace():i+=1
        if text[i]==']':return result
        begin=i;_,i=decoder.raw_decode(text,i);result.append(_members(text,begin))
        while text[i].isspace():i+=1
        if text[i]==']':return result
        if text[i]!=',':raise ValueError('Invalid task list')
        i+=1


def reconcile(files,progress,choices):
    """Return a reviewable edit draft; choices contain user-selected status/evidence.

    Each choice is {id,status,evidence}; evidence is None to retain existing
    evidence or an explicit replacement list. No model report is evidence.
    """
    progress=validate_progress(progress);snapshot=prepare_track(files,progress['track_id'])
    if snapshot['digest']!=progress['source_digest']:raise ValueError('Track or project context changed since the run; run again before reconciling')
    draft=load_edit(files,progress['track_id'])
    if prepare_track(files,progress['track_id'])!=snapshot:raise ValueError('Track changed while loading; review again')
    text=draft['files']['track.json'];track=validate_track(parse_json(text),progress['track_id'])['track']
    if not isinstance(choices,list) or len(choices)!=len(track['tasks']):raise ValueError('Supply a choice for every task')
    if [item.get('id') if isinstance(item,dict) else None for item in choices]!=[task['id'] for task in track['tasks']] or [task['id'] for task in track['tasks']]!=[item['id'] for item in progress['tasks']]:raise ValueError('Task IDs no longer match the reported progress')
    spans=_task_spans(text);replacements=[]
    for task,choice,positions in zip(track['tasks'],choices,spans):
        if set(choice)!={'id','status','evidence'}:raise ValueError('Invalid task choice')
        status=choice['status'];evidence=task['evidence'] if choice['evidence'] is None else choice['evidence']
        if status=='completed' and task['status']!='completed' and (not isinstance(evidence,list) or not evidence or any(not isinstance(item,dict) or item.get('status')!='passed' for item in evidence)):
            raise ValueError('Completing a task requires passed evidence and no failed, unknown, or unrun checks')
        if status!=task['status']:
            a,b=positions['status'];replacements.append((a,b,json.dumps(status,ensure_ascii=False)));task['status']=status
        if choice['evidence'] is not None and evidence!=task['evidence']:
            a,b=positions['evidence'];replacements.append((a,b,json.dumps(evidence,ensure_ascii=False)));task['evidence']=evidence
    validate_track(track,progress['track_id'])
    for a,b,value in sorted(replacements,reverse=True):text=text[:a]+value+text[b:]
    draft['files']['track.json']=text
    return validate_edit(draft)

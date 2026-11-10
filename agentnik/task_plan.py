"""Bounded model-reported task plans; never grant execution permission."""
import json
import unicodedata

STATUSES=('pending','in_progress','completed','blocked')


def validate_plan(value):
    if not isinstance(value,dict) or set(value)!={'explanation','steps'}:raise ValueError('Plan requires explanation and steps')
    explanation=value['explanation'];steps=value['steps']
    if not isinstance(explanation,str) or len(explanation)>1000:raise ValueError('Plan explanation must be at most 1000 characters')
    if not isinstance(steps,list) or not 1<=len(steps)<=20:raise ValueError('Plan requires 1–20 steps')
    result=[];active=0
    def control(text,newlines=False):
        return any((unicodedata.category(ch)=='Cc' and (not newlines or ch not in '\n\t')) or unicodedata.bidirectional(ch) in ('LRE','RLE','LRO','RLO','PDF','LRI','RLI','FSI','PDI') for ch in text)
    if control(explanation,True):raise ValueError('Plan contains unsupported control characters')
    for entry in steps:
        if not isinstance(entry,dict) or set(entry)!={'step','status'}:raise ValueError('Each plan step requires step and status')
        text=entry['step'];status=entry['status']
        if not isinstance(text,str) or not text.strip() or len(text)>200 or control(text):raise ValueError('Each step must be a nonempty single line of at most 200 characters')
        if not isinstance(status,str) or status not in STATUSES:raise ValueError('Use pending, in_progress, completed, or blocked')
        active+=status=='in_progress';result.append({'step':text,'status':status})
    if active>1:raise ValueError('Only one step may be in progress')
    return {'explanation':explanation,'steps':result}


def parse_update(explanation,steps):
    if not isinstance(steps,str) or len(steps.encode())>12000:raise ValueError('Plan step JSON exceeds its budget')
    try:decoded=json.loads(steps)
    except (ValueError,RecursionError):raise ValueError('Steps must be a JSON array of step/status objects') from None
    return validate_plan({'explanation':explanation,'steps':decoded})

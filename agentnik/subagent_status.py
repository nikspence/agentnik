"""Validated, bounded display records for a Code run's subagents."""
import re

STATUSES={'running','completed','failed','cancelled','interrupted','stopped'}


def validate_record(value):
    if not isinstance(value,dict) or set(value)!={'id','status','text'}:raise ValueError('Invalid subagent record')
    if not isinstance(value['id'],str) or not re.fullmatch(r'[0-9a-f]{32}-[1-3]',value['id']):raise ValueError('Invalid subagent id')
    if value['status'] not in STATUSES or not isinstance(value['text'],str) or len(value['text'])>1600:raise ValueError('Invalid subagent status')
    return dict(value)


def validate_records(values):
    if not isinstance(values,list) or len(values)>32:raise ValueError('Invalid subagent records')
    records=[validate_record(value) for value in values]
    if len({value['id'] for value in records})!=len(records):raise ValueError('Duplicate subagent record')
    return records

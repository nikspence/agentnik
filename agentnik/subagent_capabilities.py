"""Remember explicit model tool rejections without storing credentials."""
import json
from . import core
from .research import capability_key
from .tools import utc_now


def validate(config):
    records=config.get('subagent_tool_capabilities',{})
    if not isinstance(records,dict) or len(records)>256:raise ValueError('Invalid subagent capabilities')
    for key,value in records.items():
        scope=json.loads(key)
        if not isinstance(scope,list) or len(scope) not in (3,4) or not all(isinstance(item,str) for item in scope):raise ValueError('Invalid subagent capability scope')
        url,protocol,model=scope[:3];core.base_url(url)
        if protocol not in core.PROTOCOLS or not model or len(model)>1000 or (len(scope)==4 and (not scope[3] or len(scope[3])>128)):raise ValueError('Invalid subagent capability scope')
        if not isinstance(value,dict) or set(value)!={'state','at'} or value['state']!='unsupported' or not isinstance(value['at'],str) or len(value['at'])>64:raise ValueError('Invalid subagent capability')


def unsupported(config,connection):
    return config.get('subagent_tool_capabilities',{}).get(capability_key(connection),{}).get('state')=='unsupported'


def remember(config,connection):
    records=config.setdefault('subagent_tool_capabilities',{});key=capability_key(connection)
    if key not in records and len(records)>=256:records.pop(next(iter(records)))
    records[key]={'state':'unsupported','at':utc_now()}


def invalidate(config,scopes):
    records=config.get('subagent_tool_capabilities',{})
    for key in list(records):
        try:scope=json.loads(key);url,protocol=scope[:2]
        except (ValueError,TypeError):continue
        if (url,protocol) in scopes:records.pop(key,None)

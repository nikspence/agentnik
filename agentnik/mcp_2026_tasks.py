"""State and validation for MCP 2026 Tasks."""
import hashlib
import json
import copy
from datetime import datetime

from .mcp_elicitation import continuation,parse_input_required
from .mcp_support import rpc_error


TASKS_EXTENSION='io.modelcontextprotocol/tasks'
_STATUSES=frozenset(('working','input_required','completed','failed','cancelled'))
_SAFE_INTEGER=2**53-1


def _metadata(value,expected_id=None,creation=False):
    if not isinstance(value,dict) or value.get('resultType')!=('task' if creation else 'complete'):raise ValueError('Invalid MCP task response')
    ident=value.get('taskId');status=value.get('status')
    if not isinstance(ident,str) or not ident or len(ident)>1024 or any(not ch.isprintable() for ch in ident) or (expected_id is not None and ident!=expected_id):raise ValueError('Invalid MCP task identifier')
    if not isinstance(status,str) or status not in _STATUSES:raise ValueError('Invalid MCP task status')
    for key in ('createdAt','lastUpdatedAt'):
        text=value.get(key)
        if not isinstance(text,str) or not 1<=len(text)<=64:raise ValueError('Invalid MCP task timestamp')
        try:datetime.fromisoformat(text.replace('Z','+00:00'))
        except (ValueError,OverflowError):raise ValueError('Invalid MCP task timestamp') from None
    ttl=value.get('ttlMs','missing');interval=value.get('pollIntervalMs',1000)
    if ttl is not None and (type(ttl) is not int or not 0<=ttl<=_SAFE_INTEGER):raise ValueError('Invalid MCP task lifetime')
    if type(interval) is not int or not 0<=interval<=_SAFE_INTEGER:raise ValueError('Invalid MCP task polling interval')
    if 'statusMessage' in value and (not isinstance(value['statusMessage'],str) or len(value['statusMessage'])>8000):raise ValueError('Invalid MCP task status message')
    return ident,status,max(100,interval)


class TaskTracker:
    """Validate task state and prevent replay of interactive responses."""
    def __init__(self,creation):
        self.task_id,self.status,self.poll_interval_ms=_metadata(creation,creation=True)
        self.seen={};self.answered=set();self.pending=None;self.terminal=False;self.update_in_flight=False

    def request(self,method,ident=0):
        if method not in ('tasks/get','tasks/cancel') or self.terminal or type(ident) is not int or not -_SAFE_INTEGER<=ident<=_SAFE_INTEGER:raise ValueError('Invalid MCP task request')
        if method=='tasks/get' and (self.update_in_flight or self.pending is not None):raise ValueError('MCP task input is still pending')
        return {'jsonrpc':'2.0','id':ident,'method':method,'params':{'taskId':self.task_id}}

    def observe(self,value):
        if self.terminal or self.pending is not None or self.update_in_flight:raise ValueError('Unexpected MCP task response')
        _,status,interval=_metadata(value,self.task_id);self.status=status;self.poll_interval_ms=interval
        if status=='input_required':
            requests=value.get('inputRequests')
            pending=parse_input_required({'resultType':'input_required','inputRequests':requests})
            fresh=[];seen_updates={}
            for form in pending['forms']:
                key=form['id'];raw=requests[key]
                try:digest=hashlib.sha256(json.dumps(raw,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')).digest()
                except (ValueError,TypeError,UnicodeError,RecursionError):raise ValueError('Invalid MCP task input') from None
                if key in self.seen and self.seen[key]!=digest:raise ValueError('MCP task reused an input request identifier')
                seen_updates[key]=digest
                if key not in self.answered:fresh.append(form)
            if len(set(self.seen)|set(seen_updates))>1000:raise ValueError('MCP task has too many input requests')
            self.seen.update(seen_updates)
            if fresh:
                self.pending={'forms':fresh,'request_state':None}
                return {'action':'input','forms':copy.deepcopy(fresh)}
            return {'action':'poll','delay_ms':interval}
        if status=='working':return {'action':'poll','delay_ms':interval}
        self.terminal=True
        if status=='completed':
            result=value.get('result')
            if not isinstance(result,dict):raise ValueError('Invalid MCP task result')
            return {'action':'complete','result':result}
        if status=='failed':
            error=rpc_error({'error':value.get('error')})
            if self.task_id in error:error='MCP server error details were omitted.'
            return {'action':'failed','error':error}
        return {'action':'cancelled'}

    def respond(self,responses,ident=0):
        if self.terminal or self.pending is None or type(ident) is not int or not -_SAFE_INTEGER<=ident<=_SAFE_INTEGER:raise ValueError('No MCP task input is pending')
        validated=copy.deepcopy(continuation({'params':{}},self.pending,responses)['params']['inputResponses'])
        self.answered.update(validated);self.pending=None;self.update_in_flight=True
        return {'jsonrpc':'2.0','id':ident,'method':'tasks/update','params':{'taskId':self.task_id,'inputResponses':validated}}

    def acknowledge(self,value,method='tasks/update'):
        if not isinstance(value,dict) or value.get('resultType')!='complete' or set(value)-{'resultType','_meta'} or ('_meta' in value and not isinstance(value['_meta'],dict)):raise ValueError('Invalid MCP task acknowledgement')
        if method=='tasks/update' and self.update_in_flight:self.update_in_flight=False
        elif method!='tasks/cancel':raise ValueError('Unexpected MCP task acknowledgement')

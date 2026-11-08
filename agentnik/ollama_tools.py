"""Native Ollama structured tool exchanges; no execution is performed here.

Contract: https://docs.ollama.com/capabilities/tool-calling
"""
import base64
import copy
import json
import math
from pathlib import Path
from . import core
from .tools import LimitError, ResearchError, ToolCall, UncertainError


def history_messages(messages):
    history=[]; tool_bytes=0
    for m in messages:
        if not core.history_eligible(m): continue
        exchanges=m.get('research',{}).get('exchanges') if m['role']=='assistant' else None
        if exchanges:
            tool_bytes+=len(json.dumps(exchanges).encode())
            if tool_bytes>128_000: raise LimitError('Saved tool context exceeds 128 KB; open a new chat')
            history.extend(copy.deepcopy(exchanges))
        else:
            item={'role':m['role'],'content':m['text']}
            if m.get('images'): item['images']=[base64.b64encode(Path(p).read_bytes()).decode() for p in m['images']]
            history.append(item)
    return history


class CallAssembler:
    def __init__(self,limits):
        self.limits=limits; self.items={}; self.next_index=0

    def add(self,calls):
        if not isinstance(calls,list): raise ResearchError('Malformed native tool calls')
        for value in calls:
            if not isinstance(value,dict) or not isinstance(value.get('function'),dict):
                raise ResearchError('Malformed native tool call')
            fn=value['function']; index=value.get('index',fn.get('index'))
            if index is None:
                index=self.next_index; self.next_index+=1
            if type(index) is not int or index<0 or index>=self.limits.calls:
                raise LimitError('Tool call index/count limit reached')
            self.next_index=max(self.next_index,index+1)
            item=self.items.setdefault(index,{'function':{},'arguments':None})
            if 'id' in value:
                if not isinstance(value['id'],str) or len(value['id'])>200: raise ResearchError('Invalid tool call identifier')
                if 'id' in item and item['id']!=value['id']: raise ResearchError('Conflicting tool call identifiers')
                item['id']=value['id']
            name=fn.get('name')
            if name:
                if not isinstance(name,str) or len(name)>100: raise ResearchError('Invalid tool name')
                if item['function'].get('name',name)!=name: raise ResearchError('Conflicting tool call names')
                item['function']['name']=name
            if 'arguments' in fn:
                args=fn['arguments']; previous=item['arguments']
                if isinstance(args,str):
                    if previous is not None and not isinstance(previous,str): raise ResearchError('Conflicting tool arguments')
                    item['arguments']=(previous or '')+args
                elif isinstance(args,dict):
                    if previous is not None and not isinstance(previous,dict): raise ResearchError('Conflicting tool arguments')
                    merged=dict(previous or {})
                    for key,val in args.items():
                        if key in merged and merged[key]!=val: raise ResearchError('Conflicting tool arguments')
                        merged[key]=val
                    item['arguments']=merged
                else: raise ResearchError('Tool arguments must be an object or JSON text')
                if len(json.dumps(item['arguments']).encode())>self.limits.argument_bytes:
                    raise LimitError('Tool argument byte limit reached')

    def finish(self):
        calls=[]; wire=[]
        for index,item in sorted(self.items.items()):
            fn=item['function']; args=item['arguments']
            if not fn.get('name') or args is None: raise ResearchError('Incomplete tool call')
            if isinstance(args,str):
                try: args=json.loads(args)
                except (ValueError,RecursionError): raise ResearchError('Malformed streamed tool arguments') from None
            provider={'function':{'index':index,'name':fn['name'],'arguments':args}}
            if 'id' in item: provider['id']=item['id']
            calls.append(ToolCall(item.get('id',str(index)),fn['name'],args,provider)); wire.append(provider)
        return calls,wire


def request(c,body,runtime,emit,state):
    """Accumulate arguments before returning any executable call; bound NDJSON too."""
    assembler=CallAssembler(runtime.limits); size=0; completed=False
    state.update(text='',thinking='',metrics={})
    with core.open_request(c,core.endpoint(c),body,timeout=runtime.timeout()) as response:
        ctype=response.headers.get('Content-Type','')
        if body.get('stream',True) and 'ndjson' not in ctype:
            raise ResearchError('Native streaming research requires NDJSON')
        def objects():
            nonlocal size
            if 'ndjson' in ctype:
                while True:
                    runtime.check()
                    line=response.readline(runtime.limits.model_bytes+1-size)
                    if not line: break
                    size+=len(line)
                    if size>runtime.limits.model_bytes: raise LimitError('Model response byte limit reached')
                    if line.strip(): yield json.loads(line)
            else:
                data=response.read(runtime.limits.model_bytes+1)
                if len(data)>runtime.limits.model_bytes: raise LimitError('Model response byte limit reached')
                yield json.loads(data)
        for data in objects():
            runtime.check()
            if not isinstance(data,dict): raise ResearchError('Malformed native model response')
            state['metrics'].update({k:v for k,v in core.usage_metrics(data).items() if type(v) in (int,float) and math.isfinite(v) and v>=0})
            if data.get('error'): raise ResearchError(str(data['error']))
            message=data.get('message',{})
            if not isinstance(message,dict): raise ResearchError('Malformed assistant message')
            for field in ('content','thinking'):
                chunk=message.get(field,'')
                if not isinstance(chunk,str): raise ResearchError('Malformed assistant text')
                state['text' if field=='content' else 'thinking']+=chunk
            if message.get('tool_calls'): assembler.add(message['tool_calls'])
            emit({'text':state['text'],'thinking':state['thinking']})
            if data.get('done') is True:
                completed=True; break
    runtime.check()
    if not completed: raise UncertainError('Model disconnected before completion; restart explicitly')
    calls,wire=assembler.finish()
    assistant={'role':'assistant','content':state['text']}
    if state['thinking']: assistant['thinking']=state['thinking']
    if wire: assistant['tool_calls']=wire
    return assistant,calls

"""Bounded Responses SSE/JSON parsing and structured function-call continuation.

References: OpenAI Responses streaming-events and function-calling documentation.
"""
import copy
import json
import math
from . import core
from .tools import LimitError,ResearchError,ToolCall,UncertainError


def wire_tools(definitions):
    return [dict(type='function',name=d.name,description=d.description,
                 parameters=d.wire()['function']['parameters'],strict=True) for d in definitions]


def bounded_events(response,runtime):
    size=0
    if 'text/event-stream' not in response.headers.get('Content-Type',''):
        data=response.read(runtime.limits.model_bytes+1); runtime.check()
        if len(data)>runtime.limits.model_bytes: raise LimitError('Model response byte limit reached')
        yield json.loads(data); return
    pending=[]
    while True:
        runtime.check()
        raw=response.readline(runtime.limits.model_bytes+1-size)
        size+=len(raw)
        if size>runtime.limits.model_bytes: raise LimitError('Model response byte limit reached')
        if not raw:
            if pending and '\n'.join(pending)!='[DONE]': yield json.loads('\n'.join(pending))
            return
        line=raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if pending:
                text='\n'.join(pending); pending=[]
                if text=='[DONE]': return
                yield json.loads(text)
        elif line.startswith('data:'): pending.append(line[5:].lstrip())


class Accumulator:
    def __init__(self,runtime,state,emit,hosted=False,on_event=None):
        self.runtime=runtime; self.state=state; self.emit=emit; self.hosted=hosted
        self.on_event=on_event or (lambda *_:None)
        self.items={}; self.parts={}; self.annotations={}; self.thoughts={}; self.search_ids=set(); self.search_stages=set(); self.complete=False
        state.update(text='',thinking='',metrics={},output=[],annotations=[],provider_usage={},response_id='',search_activity=False)

    def index(self,data):
        index=data.get('output_index',0)
        if type(index) is not int or not 0<=index<64: raise LimitError('Responses output item limit reached')
        return index

    def search(self,ident,detail):
        if not self.hosted: raise ResearchError('Unrequested hosted web activity in managed Responses request')
        if not isinstance(ident,str) or len(ident)>200: raise ResearchError('Malformed search call ID')
        if ident not in self.search_ids:
            self.runtime.charge('calls',1,self.runtime.limits.calls); self.search_ids.add(ident)
        self.state['search_activity']=True
        stage=(ident,str(detail)[:200])
        if stage not in self.search_stages:
            self.search_stages.add(stage); self.on_event('searching',stage[1])

    def ingest_item(self,index,item):
        if not isinstance(item,dict) or item.get('type') not in ('message','reasoning','function_call','web_search_call'):
            raise ResearchError('Unexpected Responses output item')
        if len(json.dumps(item).encode())>self.runtime.limits.model_bytes: raise LimitError('Responses item byte limit reached')
        self.items[index]=copy.deepcopy(item)
        kind=item['type']
        if kind=='message':
            if item.get('role')!='assistant': raise ResearchError('Unexpected message role in Responses output')
            if not isinstance(item.get('content',[]),list) or len(item.get('content',[]))>64: raise LimitError('Content part limit reached')
            for content_index,part in enumerate(item.get('content',[])):
                if not isinstance(part,dict): raise ResearchError('Malformed Responses content')
                if part.get('type')=='output_text':
                    text=part.get('text','')
                    if not isinstance(text,str): raise ResearchError('Malformed Responses text')
                    self.parts[index,content_index]=text
                    annotations=part.get('annotations',[])
                    if not isinstance(annotations,list) or len(annotations)>100: raise LimitError('Annotation count limit reached')
                    self.annotations[index,content_index]=copy.deepcopy(annotations)
                elif part.get('type')=='refusal': self.parts[index,content_index]=str(part.get('refusal',''))
        elif kind=='reasoning':
            self.thoughts[index]='\n'.join(p['text'] for p in item.get('summary',[]) if isinstance(p,dict) and isinstance(p.get('text'),str))
        elif kind=='web_search_call': self.search(item.get('id',str(index)),item.get('status','search'))

    def refresh(self):
        state=self.state; state['text']='\n\n'.join(self.parts[k] for k in sorted(self.parts))
        state['thinking']='\n\n'.join(self.thoughts[k] for k in sorted(self.thoughts) if self.thoughts[k])
        state['output']=[copy.deepcopy(self.items[k]) for k in sorted(self.items)]
        annotated=[]; offset=0
        for key in sorted(self.parts):
            for annotation in self.annotations.get(key,[]):
                if not isinstance(annotation,dict) or annotation.get('type')!='url_citation': continue
                entry=copy.deepcopy(annotation)
                entry.update(output_index=key[0],content_index=key[1])
                for field in ('start_index','end_index'):
                    if type(entry.get(field)) is int: entry[field]+=offset
                annotated.append(entry)
            offset+=len(self.parts[key])+2
        state['annotations']=annotated
        self.emit({'text':state['text'],'thinking':state['thinking']})

    def feed(self,data):
        if not isinstance(data,dict): raise ResearchError('Malformed Responses event')
        typ=data.get('type','')
        response=data.get('response')
        if not typ and 'output' in data: response=data
        if isinstance(response,dict):
            self.state['response_id']=response.get('id',self.state['response_id'])
            if isinstance(response.get('usage'),dict):
                self.state['provider_usage']=copy.deepcopy(response['usage'])
                self.state['metrics'].update({k:v for k,v in core.usage_metrics(response).items() if type(v) in (int,float) and math.isfinite(v) and v>=0})
            if 'output' in response:
                output=response['output']
                if not isinstance(output,list) or len(output)>64: raise LimitError('Responses output item limit reached')
                if output or not self.parts:
                    self.items={}; self.parts={}; self.annotations={}; self.thoughts={}
                    for index,item in enumerate(output): self.ingest_item(index,item)
        if typ in ('response.output_item.added','response.output_item.done'):
            self.ingest_item(self.index(data),data.get('item'))
        elif typ in ('response.output_text.delta','response.output_text.done'):
            key=self.index(data),data.get('content_index',0)
            if type(key[1]) is not int or not 0<=key[1]<64: raise ResearchError('Malformed content index')
            text=data.get('delta' if typ.endswith('delta') else 'text','')
            if not isinstance(text,str): raise ResearchError('Malformed text delta')
            self.parts[key]=self.parts.get(key,'')+text if typ.endswith('delta') else text
        elif typ=='response.output_text.annotation.added':
            key=self.index(data),data.get('content_index',0)
            if type(key[1]) is not int or not 0<=key[1]<64: raise ResearchError('Malformed annotation index')
            entries=self.annotations.setdefault(key,[])
            if len(entries)>=100: raise LimitError('Citation annotation limit reached')
            entries.append(copy.deepcopy(data.get('annotation')))
        elif typ in ('response.function_call_arguments.delta','response.function_call_arguments.done'):
            index=self.index(data); item=self.items.get(index)
            if not item or item.get('type')!='function_call': raise ResearchError('Arguments arrived without a function call')
            chunk=data.get('delta' if typ.endswith('delta') else 'arguments','')
            if not isinstance(chunk,str): raise ResearchError('Malformed function arguments')
            item['arguments']=item.get('arguments','')+chunk if typ.endswith('delta') else chunk
            if len(item['arguments'].encode())>self.runtime.limits.argument_bytes: raise LimitError('Tool argument byte limit reached')
        elif typ in ('response.reasoning_summary_text.delta','response.reasoning_text.delta'):
            index=self.index(data); chunk=data.get('delta','')
            if not isinstance(chunk,str): raise ResearchError('Malformed thinking delta')
            self.thoughts[index]=self.thoughts.get(index,'')+chunk
        elif typ.startswith('response.web_search_call.'):
            self.search(data.get('item_id',str(self.index(data))),typ.rsplit('.',1)[-1])
        self.refresh()
        if typ in ('response.failed','response.incomplete','error'):
            raise ResearchError('Provider response ended '+('failed' if typ=='error' else typ.rsplit('.',1)[-1])+'; restart explicitly')
        if typ=='response.completed' or (not typ and isinstance(response,dict)):
            if not isinstance(response,dict) or response.get('status')!='completed':
                raise ResearchError('Responses request did not complete; restart explicitly')
            self.complete=True


def request(c,body,runtime,emit,state,hosted=False,on_event=None):
    accumulator=Accumulator(runtime,state,emit,hosted,on_event)
    with core.open_request(c,core.endpoint(c),body,timeout=runtime.timeout()) as response:
        for data in bounded_events(response,runtime):
            runtime.check(); accumulator.feed(data)
            if accumulator.complete: break
    runtime.check()
    if not accumulator.complete: raise UncertainError('Responses disconnected before completion; restart explicitly')
    calls=[]; seen=set()
    for item in state['output']:
        if item.get('type')=='function_call':
            if hosted: raise ResearchError('Unregistered function call in hosted search output')
            ident=item.get('call_id'); args=item.get('arguments'); name=item.get('name')
            if not all(isinstance(v,str) and v for v in (ident,args,name)) or len(ident)>200 or len(name)>100:
                raise ResearchError('Malformed Responses function call')
            if len(args.encode())>runtime.limits.argument_bytes: raise LimitError('Tool argument byte limit reached')
            if ident in seen: raise ResearchError('Duplicate Responses call ID')
            seen.add(ident)
            calls.append(ToolCall(ident,name,args,copy.deepcopy(item)))
    if len(calls)>runtime.limits.calls: raise LimitError('Tool call limit reached')
    return state['output'],calls

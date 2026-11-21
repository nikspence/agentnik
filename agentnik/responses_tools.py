"""Bounded Responses SSE/JSON parsing and structured function-call continuation.

References: OpenAI Responses streaming-events and function-calling documentation.
"""
import copy
import json
import math
from . import core
from .tools import LimitError,ResearchError,ToolCall,UncertainError


class ResponseIdentityError(ResearchError):
    """Conflicting locally classified identity fields; values remain private."""
    def __init__(self,field,stage,previous,item,item_type,call_fields=None,other_match=False):
        self.field=field
        self.stage=stage if stage in ('output_item.added','output_item.done','response.completed','response.snapshot') else 'other'
        self.item_type=item_type if item_type in ('message','reasoning','function_call','web_search_call') else 'other'
        def shape(value):
            if value is None:return 'null'
            if isinstance(value,str):return 'empty' if not value else 'text'
            return 'other'
        self.shapes=(shape(previous),shape(item))
        self.call_fields=call_fields or {}
        self.other_match=bool(other_match)
        super().__init__('Conflicting Responses item identity')


def same_call_arguments(left,right):
    if not isinstance(left,str) or not isinstance(right,str) or not left or not right:return False
    if left==right:return True
    def object_without_duplicates(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate key')
            result[key]=value
        return result
    try:
        def canonical(value):
            parsed=json.loads(value,object_pairs_hook=object_without_duplicates,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Invalid constant')))
            if not isinstance(parsed,dict):raise ValueError('Arguments must be an object')
            return json.dumps(parsed,sort_keys=True,ensure_ascii=True,separators=(',',':'))
        return canonical(left)==canonical(right)
    except (ValueError,TypeError,RecursionError):return False


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
        self.items={}; self.parts={}; self.annotations={}; self.thoughts={}; self.search_ids=set(); self.search_stages=set(); self.complete=False; self.closed_items=set(); self.closed_arguments=set()
        state.update(text='',thinking='',metrics={},output=[],annotations=[],provider_usage={},response_id='',search_activity=False)

    def index(self,data):
        index=data.get('output_index',0)
        if type(index) is not int or not 0<=index<max(64,self.runtime.limits.calls): raise LimitError('Responses output item limit reached')
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

    def ingest_item(self,index,item,stage='other',previous_items=None):
        if not isinstance(item,dict) or item.get('type') not in ('message','reasoning','function_call','web_search_call'):
            raise ResearchError('Unexpected Responses output item')
        if len(json.dumps(item).encode())>self.runtime.limits.model_bytes: raise LimitError('Responses item byte limit reached')
        previous=self.items.get(index)
        if previous:
            # Some gateways replace a function-call item's transport ID in the
            # final snapshot. Only accept that change when the executable call
            # itself is fully identified and unchanged; never infer correlation
            # from the item ID alone or accept changed arguments.
            def compare(key):
                left,right=previous.get(key),item.get(key)
                if not isinstance(left,str) or not left:return 'stream_missing'
                if not isinstance(right,str) or not right:return 'final_missing'
                equal=same_call_arguments(left,right) if key=='arguments' else left==right
                return 'same' if equal else 'different'
            comparison={key:compare(key) for key in ('call_id','name','arguments')}
            other_match=any(other_index!=index and isinstance(other,dict) and other.get('type')=='function_call'
                            and isinstance(item.get('call_id'),str) and item['call_id']
                            and item['call_id']==other.get('call_id')
                            for other_index,other in (previous_items or {}).items())
            same_call=(stage=='response.completed' and previous.get('type')=='function_call'
                       and item.get('type')=='function_call'
                       and all(value=='same' for value in comparison.values()))
            for field in ('type','id','call_id','name'):
                if field in previous and field in item and previous[field]!=item[field]:
                    if field=='id' and same_call:continue
                    raise ResponseIdentityError(field,stage,previous[field],item[field],item.get('type'),comparison if item.get('type')=='function_call' else None,other_match)
            if stage=='response.completed' and previous.get('type')=='function_call' and previous.get('id')!=item.get('id') and not same_call:
                raise ResponseIdentityError('id',stage,previous.get('id'),item.get('id'),item.get('type'),comparison,other_match)
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
                start,end=entry.get('start_index'),entry.get('end_index')
                if type(start) is int and type(end) is int and 0<=start<=end<=len(self.parts[key]):
                    entry['start_index']=start+offset; entry['end_index']=end+offset
                else:
                    # Keep the invalid annotation count, without allowing its span
                    # to point into a different content block after concatenation.
                    entry['start_index']=entry['end_index']=None
                annotated.append(entry)
            offset+=len(self.parts[key])+2
        state['annotations']=annotated
        self.emit({'text':state['text'],'thinking':state['thinking']})

    def feed(self,data):
        if self.complete: raise ResearchError('Responses event after completion')
        if not isinstance(data,dict): raise ResearchError('Malformed Responses event')
        typ=data.get('type','')
        response=data.get('response')
        if not typ and 'output' in data: response=data
        terminal=typ=='response.completed' or (not typ and isinstance(response,dict))
        if terminal and (not isinstance(response,dict) or not isinstance(response.get('output'),list)):
            raise ResearchError('Completed Responses object missing output')
        if isinstance(response,dict):
            self.state['response_id']=response.get('id',self.state['response_id'])
            if isinstance(response.get('usage'),dict):
                self.state['provider_usage']=core.merge_usage(self.state['provider_usage'],response['usage'])
                self.state['metrics'].update({k:v for k,v in core.usage_metrics(dict(response,usage=self.state['provider_usage'])).items() if type(v) in (int,float) and math.isfinite(v) and v>=0})
            if 'output' in response:
                output=response['output']
                if not isinstance(output,list) or len(output)>max(64,self.runtime.limits.calls): raise LimitError('Responses output item limit reached')
                if terminal or output or not self.parts:
                    previous_items=self.items
                    self.items={}; self.parts={}; self.annotations={}; self.thoughts={}
                    # A gateway may reorder function calls in the completed
                    # snapshot. Correlate only unique, nonempty call IDs and
                    # verify the complete call before accepting a moved item.
                    prior_calls={}
                    if terminal:
                        for prior_index,prior in previous_items.items():
                            ident=prior.get('call_id') if isinstance(prior,dict) and prior.get('type')=='function_call' else None
                            if isinstance(ident,str) and ident:
                                if ident in prior_calls:raise ResearchError('Duplicate Responses call ID')
                                prior_calls[ident]=prior_index
                    final_ids=set()
                    for item in output:
                        ident=item.get('call_id') if isinstance(item,dict) and item.get('type')=='function_call' else None
                        if isinstance(ident,str) and ident:
                            if ident in final_ids:raise ResearchError('Duplicate Responses call ID')
                            final_ids.add(ident)
                    claimed=set()
                    for index,item in enumerate(output):
                        ident=item.get('call_id') if isinstance(item,dict) and item.get('type')=='function_call' else None
                        previous_index=prior_calls.get(ident,index) if isinstance(ident,str) and ident else index
                        if previous_index in previous_items and previous_index not in claimed:
                            prior=previous_items[previous_index]
                            if previous_index!=index:
                                if not (isinstance(prior.get('name'),str) and prior['name'] and prior['name']==item.get('name') and same_call_arguments(prior.get('arguments'),item.get('arguments'))):
                                    raise ResponseIdentityError('id','response.completed',prior.get('id'),item.get('id'),'function_call',{'call_id':'same','name':'different' if prior.get('name')!=item.get('name') else 'same','arguments':'same' if same_call_arguments(prior.get('arguments'),item.get('arguments')) else 'different'},True)
                            self.items[index]=prior;claimed.add(previous_index)
                        self.ingest_item(index,item,'response.completed' if terminal else 'response.snapshot',previous_items)
        if typ=='response.output_item.added' and self.index(data) in self.items:
            raise ResearchError('Duplicate Responses output item')
        if typ in ('response.output_item.added','response.output_item.done'):
            index=self.index(data)
            if index in self.closed_items: raise ResearchError('Responses item after closure')
            self.ingest_item(index,data.get('item'),typ.removeprefix('response.'))
            if typ.endswith('.done'): self.closed_items.add(index)
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
            if index in self.closed_items or index in self.closed_arguments: raise ResearchError('Arguments after closure')
            if item and data.get('item_id',item.get('id'))!=item.get('id'): raise ResearchError('Conflicting argument item ID')
            if typ.endswith('.done'): self.closed_arguments.add(index)
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
            if item.get('status') not in (None,'completed'): raise ResearchError('Incomplete Responses function call')
            ident=item.get('call_id'); args=item.get('arguments'); name=item.get('name')
            if not all(isinstance(v,str) and v for v in (ident,args,name)) or len(ident)>200 or len(name)>100:
                raise ResearchError('Malformed Responses function call')
            if len(args.encode())>runtime.limits.argument_bytes: raise LimitError('Tool argument byte limit reached')
            if ident in seen: raise ResearchError('Duplicate Responses call ID')
            seen.add(ident)
            calls.append(ToolCall(ident,name,args,copy.deepcopy(item)))
    if len(calls)>runtime.limits.calls: raise LimitError('Tool call limit reached')
    return state['output'],calls

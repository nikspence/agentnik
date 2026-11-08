"""Protocol-specific Chat Completions and Messages research adapters."""
import copy,json,math
from . import core
from .responses_tools import bounded_events
from .tools import LimitError,ResearchError,UncertainError,ToolCall


def wire_tools(definitions,protocol):
    if protocol=='messages':
        return [{'name':d.name,'description':d.description,'input_schema':d.wire()['function']['parameters']} for d in definitions]
    return [d.wire() for d in definitions]


def request(c,body,runtime,emit,state):
    messages=c.get('protocol')=='messages'
    state.update(text='',thinking='',metrics={})
    blocks={}; fragments={}; closed=set(); calls={}; finish=None; stopped=False
    def usage(data):
        state['metrics'].update({k:v for k,v in core.usage_metrics(data).items() if type(v) in (int,float) and math.isfinite(v) and v>=0})
    def block_index(data):
        index=data.get('index')
        if type(index) is not int or not 0<=index<64: raise ResearchError('Invalid content/tool index')
        return index
    with core.open_request(c,core.endpoint(c),body,timeout=runtime.timeout()) as response:
        for data in bounded_events(response,runtime):
            runtime.check()
            if not isinstance(data,dict): raise ResearchError('Malformed protocol response')
            if data.get('error') or data.get('type')=='error': raise ResearchError('Provider stream error; restart explicitly')
            usage(data)
            if messages:
                typ=data.get('type')
                if typ=='message_start': usage(data.get('message',{}))
                elif typ=='content_block_start':
                    i=block_index(data)
                    if i in blocks: raise ResearchError('Duplicate content block')
                    blocks[i]=copy.deepcopy(data['content_block'])
                elif typ=='content_block_delta':
                    i=block_index(data)
                    if i not in blocks or i in closed: raise ResearchError('Delta outside an open content block')
                    delta=data.get('delta',{}); kind=delta.get('type'); block=blocks[i]
                    allowed={'text_delta':('text','text','text'),'thinking_delta':('thinking','thinking','thinking'),
                             'signature_delta':('thinking','signature','signature')}
                    if kind=='input_json_delta':
                        if block.get('type')!='tool_use': raise ResearchError('JSON outside tool block')
                        fragment=delta.get('partial_json')
                        if not isinstance(fragment,str): raise ResearchError('Malformed tool JSON fragment')
                        fragments[i]=fragments.get(i,'')+fragment
                        if len(fragments[i].encode())>runtime.limits.argument_bytes: raise LimitError('Tool argument limit reached')
                    elif kind in allowed:
                        expected,field,source=allowed[kind]
                        if block.get('type')!=expected or not isinstance(delta.get(source),str): raise ResearchError('Mismatched content delta')
                        block[field]=block.get(field,'')+delta[source]
                    else: raise ResearchError('Unsupported content delta')
                elif typ=='content_block_stop':
                    i=block_index(data)
                    if i not in blocks or i in closed: raise ResearchError('Invalid content block stop')
                    if i in fragments:
                        try: blocks[i]['input']=json.loads(fragments[i])
                        except (ValueError,RecursionError): raise ResearchError('Malformed streamed tool JSON') from None
                    closed.add(i)
                elif typ=='message_delta': finish=data.get('delta',{}).get('stop_reason',finish)
                elif typ=='message_stop': stopped=True
                elif isinstance(data.get('content'),list):
                    blocks={i:copy.deepcopy(b) for i,b in enumerate(data['content'])}; closed=set(blocks)
                    finish=data.get('stop_reason'); stopped=True
                elif typ not in ('ping',): raise ResearchError('Unexpected Messages event')
                if len(blocks)>64: raise LimitError('Content block limit reached')
                for b in blocks.values():
                    if b.get('type') not in ('text','thinking','redacted_thinking','tool_use'): raise ResearchError('Unregistered server content block')
                state['text']=''.join(b.get('text','') for _,b in sorted(blocks.items()) if b.get('type')=='text')
                state['thinking']=''.join(b.get('thinking','') for _,b in sorted(blocks.items()) if b.get('type')=='thinking')
            else:
                choices=data.get('choices',[])
                if len(choices)>1: raise ResearchError('Multiple completion choices are not supported')
                if choices:
                    choice=choices[0]; delta=choice.get('delta') or choice.get('message') or {}
                    state['text']+=delta.get('content') or ''
                    state['thinking']+=delta.get('reasoning_content') or ''
                    for pos,call in enumerate(delta.get('tool_calls',[])):
                        if call.get('type','function')!='function': raise ResearchError('Unregistered tool type')
                        i=call.get('index',pos)
                        if type(i) is not int or not 0<=i<runtime.limits.calls: raise LimitError('Tool index limit reached')
                        current=calls.setdefault(i,{'id':'','type':'function','function':{'name':'','arguments':''}})
                        if call.get('id'):
                            if current['id'] and current['id']!=call['id']: raise ResearchError('Conflicting tool ID')
                            current['id']=call['id']
                        fn=call.get('function',{})
                        for field in ('name','arguments'):
                            value=fn.get(field,'')
                            if not isinstance(value,str): raise ResearchError('Malformed function fragment')
                            current['function'][field]+=value
                        if len(json.dumps(current).encode())>runtime.limits.argument_bytes: raise LimitError('Tool argument limit reached')
                    if choice.get('finish_reason') is not None: finish=choice['finish_reason']
            emit({'text':state['text'],'thinking':state['thinking']})
    runtime.check()
    if messages:
        if not stopped or closed!=set(blocks): raise UncertainError('Messages disconnected before completion')
        if finish not in ('tool_use','end_turn','stop_sequence'): raise ResearchError('Messages turn incomplete: '+str(finish))
        assistant={'role':'assistant','content':[blocks[i] for i in sorted(blocks)]}
        wire=[b for b in assistant['content'] if b.get('type')=='tool_use']
        if bool(wire)!=(finish=='tool_use'): raise ResearchError('Inconsistent tool stop reason')
        if wire and any(b.get('type')=='thinking' and not b.get('signature') for b in assistant['content']):
            raise ResearchError('Thinking signature missing before tool continuation')
        result=[ToolCall(b.get('id',''),b.get('name',''),b.get('input'),copy.deepcopy(b)) for b in wire]
    else:
        if finish is None: raise UncertainError('Chat stream disconnected before completion')
        if finish not in ('stop','tool_calls'): raise ResearchError('Chat turn incomplete: '+str(finish))
        wire=[calls[i] for i in sorted(calls)]
        if bool(wire)!=(finish=='tool_calls'): raise ResearchError('Inconsistent tool stop reason')
        assistant={'role':'assistant','content':state['text']}
        if state['thinking']: assistant['reasoning_content']=state['thinking']
        if wire: assistant['tool_calls']=wire
        result=[ToolCall(b['id'],b['function']['name'],b['function']['arguments'],copy.deepcopy(b)) for b in wire]
    seen=set()
    for call in result:
        if not isinstance(call.id,str) or not call.id or len(call.id)>200 or call.id in seen: raise ResearchError('Missing or duplicate tool identifier')
        if not isinstance(call.name,str) or not call.name or len(call.name)>100: raise ResearchError('Invalid tool name')
        if len(json.dumps(call.arguments).encode())>runtime.limits.argument_bytes: raise LimitError('Tool arguments too large')
        seen.add(call.id)
    if len(result)>runtime.limits.calls: raise LimitError('Tool call limit reached')
    return assistant,result

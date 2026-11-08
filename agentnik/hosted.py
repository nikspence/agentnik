"""OpenAI Responses hosted search: explicit endpoint/model opt-in, no managed execution."""
import copy
from dataclasses import asdict
import json
import re
import time
from . import core,responses_tools
from .failures import classify
from .research import scrub
from .tools import AccessError,LimitError,ResearchError,ResearchEvent,RouteAttempt,Runtime,utc_now
from .web import public_url


def supported_endpoint(c):
    return c.get('protocol')=='responses' and core.base_url(c['url'])=='https://api.openai.com/v1'


def run_hosted(c,messages,key,emit,cancel,limits=None,run_id=None,runtime=None):
    owned=runtime is None; runtime=runtime or Runtime(cancel,limits,run_id)
    start=time.monotonic(); route=RouteAttempt('hosted','openai-web-search')
    state={'version':2,'run_id':runtime.run_id,'route':'hosted','status':'running','events':[],
           'sources':[],'annotations':[],'exchanges':[],'response_items':[],'provider_usage':[],
           'attempts':[asdict(route)],'capability_state':'configured','protocol':'responses','limits':asdict(runtime.limits)}
    result={'text':'','thinking':'','metrics':{},'research':state,'status':'failed'}
    active={}; requested=0; model_seconds=0
    secrets=(c.get('api_key',''),key)
    previous_ids=[int(s['id'][1:]) for m in messages for s in m.get('research',{}).get('sources',[]) if re.fullmatch(r'S\d+',s.get('id',''))]
    next_id=max(previous_ids,default=0)+1; by_url={}
    def source(url,title='',annotation=False):
        nonlocal next_id
        url=public_url(url)
        if url in by_url:
            ident=by_url[url]
            if title:
                for saved in state['sources']:
                    if saved['id']==ident and saved['title']==url: saved['title']=title[:300]
            return ident
        if len(state['sources'])>=runtime.limits.results*runtime.limits.calls: raise LimitError('Hosted source retention limit reached')
        ident=f'S{next_id}'; next_id+=1; by_url[url]=ident
        state['sources'].append({'id':ident,'title':title[:300] or url,'url':url,'excerpt':'','retrieved_at':'',
                                 'reported_at':utc_now(),'content_type':'text/plain','truncated':False,
                                 'backend':'openai-hosted','metadata_only':True})
        return ident
    def collect():
        state['response_items']=copy.deepcopy(active.get('output',[]))
        state['response_id']=active.get('response_id','')
        if active.get('provider_usage'): state['provider_usage']=[copy.deepcopy(active['provider_usage'])]
        annotations=[]; invalid=0
        for entry in active.get('annotations',[]):
            if not isinstance(entry.get('url'),str): invalid+=1; continue
            ident=source(entry['url'],str(entry.get('title','')),True)
            start_index,end_index=entry.get('start_index'),entry.get('end_index')
            if type(start_index) is not int or type(end_index) is not int or not 0<=start_index<=end_index<=len(active.get('text','')):
                invalid+=1; continue
            annotations.append(dict(entry,source_id=ident))
        for item in active.get('output',[]):
            if item.get('type')!='web_search_call': continue
            action=item.get('action',{})
            if not isinstance(action,dict): raise ResearchError('Malformed hosted search action')
            for entry in action.get('sources',[]):
                if isinstance(entry,dict) and isinstance(entry.get('url'),str): source(entry['url'],str(entry.get('title','')))
            if action.get('type') in ('open_page','find_in_page') and isinstance(action.get('url'),str): source(action['url'])
        state['unverified_citations']=sorted({m.group(1) for m in re.finditer(r'\[(S\d+)\]',active.get('text','')) if not any(a['start_index']<=m.start() and a['end_index']>=m.end() for a in annotations)})
        state['annotations']=annotations
        state['unverified_annotations']=invalid
        state['citations']=sorted({a['source_id'] for a in annotations})
        state['hosted_calls']=len({i.get('id',str(n)) for n,i in enumerate(active.get('output',[])) if i.get('type')=='web_search_call'})
        if active.get('search_activity'): state['capability_state']='verified'
    def snapshot():
        value=copy.deepcopy(result)
        current=dict(active.get('metrics',{})); current.update(total_seconds=time.monotonic()-start,model_requests=requested,
              usage_complete=requested>0 and all(k in current for k in ('input_tokens','output_tokens')),model_seconds=model_seconds)
        if 'input_tokens' in current: current['last_input_tokens']=current['input_tokens']
        value['metrics']=current
        clean=scrub(value,secrets)
        if clean['text']!=value['text']:
            clean['research']['unverified_annotations']=len(clean['research'].get('annotations',[]))
            clean['research']['annotations']=[]; clean['research']['citations']=[]
        return clean
    def event(kind,detail):
        runtime.check()
        if len(state['events'])>=100: raise LimitError('Hosted event retention limit reached')
        state['events'].append(asdict(ResearchEvent(runtime.run_id,kind,str(detail)[:500])))
        emit(snapshot())
    def progress(value):
        runtime.check(); result.update(value); collect(); emit(snapshot())
    try:
        runtime.check()
        if not supported_endpoint(c): raise AccessError('Hosted search is restricted to the explicitly configured official OpenAI Responses endpoint')
        body=core.chat_body(c,messages)
        remaining=runtime.limits.calls-runtime.calls
        if remaining<=0: raise LimitError('Hosted tool call limit reached')
        body.update(tools=[{'type':'web_search'}],store=False,include=['web_search_call.action.sources','reasoning.encrypted_content'],max_tool_calls=remaining)
        event('route','Provider-hosted OpenAI web search; provider navigation cannot be constrained by Agentnik')
        runtime.charge('requests',1,runtime.limits.requests); requested=1
        event('model','Hosted Responses request')
        model_start=time.monotonic()
        try: runtime.wait(lambda:responses_tools.request(c,body,runtime,progress,active,hosted=True,on_event=event))
        finally: model_seconds=time.monotonic()-model_start
        collect()
        runtime.charge('context_bytes',len(json.dumps(state['response_items']).encode()),runtime.limits.context_bytes)
        result.update(text=active['text'],thinking=active['thinking'],status='ok')
        state['status']='completed'; route.status='completed'
        event('completed','Provider-hosted search completed' if active.get('search_activity') else 'Provider answered without invoking search')
    except Exception as exc:
        if isinstance(exc,core.EndpointError):
            active.setdefault('metrics',{}).update(core.usage_metrics(exc.payload if isinstance(exc.payload,dict) else {}))
        partial=bool(result['text'] or result['thinking'] or active.get('search_activity') or state['sources'] or state['response_items'] or active.get('metrics',{}).get('output_tokens',0)>0)
        failure=classify(exc,partial,tool='web_search'); state['failure']=failure
        if failure['kind']=='unsupported': state['capability_state']='unsupported'
        state['status']='cancelled' if isinstance(exc,InterruptedError) else 'limited' if isinstance(exc,LimitError) else 'failed'
        route.status=state['status']; result.update(status='failed',error=str(exc)[:1000])
        state['events'].append(asdict(ResearchEvent(runtime.run_id,state['status'],result['error'])))
    route.ended_at=utc_now(); state['attempts']=[asdict(route)]
    value=snapshot()
    if owned: runtime.closed=True
    return value

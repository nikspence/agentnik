"""Explicit route selection, bounded retries, and a shared attempt/usage ledger."""
import copy
from dataclasses import asdict
import time
from . import core,research,hosted
from .tools import AccessError,LimitError,ResearchEvent,Runtime,utc_now
from .web import OrderedSearch

POLICIES=('Provider first','Agentnik first','Provider only','Agentnik only')
ACCESS_POLICIES=('public_fetch','strict_public')


def defaults_key(name,c):
    import json
    return json.dumps([name,core.base_url(c['url']),c.get('protocol','chat')],separators=(',',':'))


def connection_defaults(config,name,c):
    value=config.get('research_defaults',{}).get(defaults_key(name,c),{})
    return {'policy':value.get('policy','Provider first'),'access_policy':value.get('access_policy','public_fetch')}


def save_defaults(config,name,c,policy,access_policy):
    if policy not in POLICIES or access_policy not in ACCESS_POLICIES: raise ValueError('Invalid research defaults')
    config.setdefault('research_defaults',{})[defaults_key(name,c)]={'policy':policy,'access_policy':access_policy}


def eligible(route,c,config,backends,access_policy):
    if access_policy=='strict_public': return 'Selected strict policy cannot be enforced inside externally navigated search services'
    if route=='hosted':
        if not hosted.supported_endpoint(c): return 'Hosted adapter requires the official OpenAI Responses connection'
        field='hosted_search'
    else:
        if c.get('protocol','chat') not in core.PROTOCOLS: return 'Unsupported managed protocol'
        field='managed_tools'
    state=research.capability(config,c,field).state
    if state not in ('configured','verified'): return f'{field}: {state}; configure this endpoint/model explicitly'
    if route=='managed' and not any(b.get('key') and b.get('kind')=='ollama' for b in backends): return 'No managed search backend credential is configured'
    return ''


def aggregate(values,runtime):
    metrics={}; last=None; complete=True; requests=0; timed=True; generation_seconds=generated=0
    for value in values:
        m=value.get('metrics',{}); n=m.get('model_requests',0); requests+=n
        if n and not m.get('usage_complete',False): complete=False
        for field in ('input_tokens','output_tokens','tool_seconds','model_seconds'):
            if field in m: metrics[field]=metrics.get(field,0)+m[field]
        if n: last=m.get('last_input_tokens')
        if n:
            if 'generation_seconds' not in m or 'output_tokens' not in m: timed=False
            else: generation_seconds+=m['generation_seconds']; generated+=m['output_tokens']
    metrics.update(model_requests=requests,usage_complete=complete and requests>0,total_seconds=time.monotonic()-runtime.started)
    if requests: metrics['last_input_tokens']=last
    if timed and generation_seconds: metrics.update(generation_seconds=generation_seconds,generation_tps=generated/generation_seconds)
    return metrics


def run(c,messages,key,emit,cancel,config,policy,backends,access_policy,limits=None,run_id=None,backend=None):
    runtime=Runtime(cancel,limits,run_id); c=copy.deepcopy(c); messages=copy.deepcopy(messages)
    if policy not in POLICIES or access_policy not in ACCESS_POLICIES: raise ValueError('Invalid research policy')
    specs=copy.deepcopy(backends if backends is not None else [{'id':'ollama-search','kind':'ollama','name':'Ollama search','key':key}])
    if len(specs)>5: raise ValueError('At most five managed search backends are supported')
    secrets=(c.get('api_key',''),key,*[b.get('key','') for b in specs])
    order={'Provider first':['hosted','managed'],'Agentnik first':['managed','hosted'],
           'Provider only':['hosted'],'Agentnik only':['managed']}[policy]
    attempts=[]; events=[]; completed=[]; updates=[]; last=None
    def empty():
        return {'text':'','thinking':'','metrics':{},'status':'failed',
                'research':{'version':2,'run_id':runtime.run_id,'status':'failed','events':[],'sources':[],
                            'exchanges':[],'response_items':[],'attempts':[]}}
    def merged(value):
        out=copy.deepcopy(value); state=out['research']
        state.update(version=2,policy=policy,access_policy=access_policy,capability_updates=copy.deepcopy(updates))
        state['attempts']=copy.deepcopy(attempts)+state.get('attempts',[])
        state['events']=copy.deepcopy(events)+state.get('events',[])
        out['metrics']=aggregate(completed+[value],runtime)
        return research.scrub(out,secrets)
    def notice(kind,detail):
        runtime.check(); events.append(asdict(ResearchEvent(runtime.run_id,kind,detail[:500])))
        value=empty(); value['research']['status']='running'; emit(merged(value))
    try:
        for route in order:
            runtime.check()
            reason=eligible(route,c,config,specs,access_policy)
            if reason:
                attempts.append({'route':route,'status':'skipped','reason':reason,'started_at':utc_now(),'ended_at':utc_now()})
                notice('route_skipped',route+': '+reason); continue
            notice('route_selected',route+': '+policy)
            for retry in range(2):
                runtime.check()
                if len(attempts)>=runtime.limits.attempts: raise LimitError('Research attempt limit reached')
                if route=='managed':
                    service=backend or OrderedSearch(specs,allow_fallback=True)
                    last=research.run_managed(c,messages,key,lambda v:emit(merged(v)),cancel,backend=service,runtime=runtime)
                else:
                    last=hosted.run_hosted(c,messages,key,lambda v:emit(merged(v)),cancel,runtime=runtime)
                state=last['research']; capability_state=state.get('capability_state')
                if capability_state in ('verified','unsupported'):
                    updates.append({'field':'hosted_search' if route=='hosted' else 'managed_tools','state':capability_state,
                                    'evidence':f'{route} route observed '+capability_state})
                for attempt in state.get('attempts',[]):
                    attempt['usage']=copy.deepcopy(last['metrics']); attempt['retry']=retry
                if last['status']=='ok':
                    value=merged(last); runtime.closed=True; return value
                failure=state.get('failure',{}); kind=failure.get('kind')
                # Never replay after partial activity or an uncertain/access/cancelled outcome.
                if not failure.get('fallback_allowed',False):
                    value=merged(last); runtime.closed=True; return value
                if kind in ('rate_limit','temporary'):
                    delay=failure.get('retry_after')
                    if delay is None: delay=.25
                    if delay>runtime.limits.backoff_seconds:
                        last['error']='Provider retry guidance exceeds the bounded wait; wait and restart explicitly'
                        value=merged(last); runtime.closed=True; return value
                    completed.append(last); attempts.extend(state.get('attempts',[])); events.extend(state.get('events',[])); last=None
                    notice('retry_wait',f'{delay:g}s before another eligible attempt')
                    runtime.pause(delay)
                    if retry==0:
                        notice('retry',route+': one bounded retry'); continue
                    break
                completed.append(last); attempts.extend(state.get('attempts',[])); events.extend(state.get('events',[])); last=None
                break
            notice('route_switch' if route!=order[-1] else 'route_stopped',route+' did not complete; '+('considering the next eligible route' if route!=order[-1] else 'policy permits no further route'))
        last=empty(); last['error']='No eligible research route completed; review the recorded reasons and settings'
        return merged(last)
    except Exception as exc:
        value=last or empty(); value['status']='failed'; value['error']=str(exc)[:1000]
        value['research']['status']='cancelled' if isinstance(exc,InterruptedError) else 'limited' if isinstance(exc,LimitError) else 'failed'
        events.append(asdict(ResearchEvent(runtime.run_id,value['research']['status'],value['error'])))
        return merged(value)
    finally: runtime.closed=True

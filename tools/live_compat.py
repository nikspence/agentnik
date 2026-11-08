"""Explicit, bounded live compatibility checks. Planning is the default."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agentnik import core, hosted, research, compat_tools, responses_tools, ollama_tools
from agentnik.citations import cited_markdown
from agentnik.tools import Limits, Runtime, ResearchError

CHAT_PROMPT='Reply with exactly: Agentnik connected'
WEB_PROMPT=('Search once for official Ollama web search API documentation, then fetch one official public page from those results. '
            'Briefly state the search endpoint and authentication method, citing your sources. At most one search and one fetch.')
HOSTED_PROMPT='Use web search to find official Ollama web search API documentation. Briefly state its endpoint and cite your sources.'


def revision():
    try:
        args=['git','-c','safe.directory='+ROOT.as_posix()]
        commit=subprocess.run([*args,'rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,timeout=5,check=True).stdout.strip()
        dirty=bool(subprocess.run([*args,'status','--porcelain'],cwd=ROOT,capture_output=True,text=True,timeout=5,check=True).stdout.strip())
        return {'commit':commit,'dirty':dirty}
    except (OSError,subprocess.SubprocessError): return {'commit':'unknown','dirty':None}


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',required=True);p.add_argument('--model',required=True)
    p.add_argument('--protocol',required=True,choices=core.PROTOCOLS)
    p.add_argument('--route',required=True,choices=('chat','managed','hosted'))
    p.add_argument('--backend',choices=('ollama',));p.add_argument('--key-file',type=Path)
    p.add_argument('--search-key-file',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--execute',action='store_true',help='Authorize the displayed live requests; default only prints a plan')
    p.add_argument('--no-stream',action='store_true')
    return p


def summarize(result,c,route):
    state=result.get('research',{});records=state.get('tool_records',[]);sources=state.get('sources',[])
    completed=[r for r in records if r.get('status')=='completed']
    ids={s.get('id') for s in sources}
    references=set(re.findall(r'\[(S\d+)\]',result.get('text','')))
    search=any(r.get('name')=='web_search' for r in completed) and any(s.get('backend')=='ollama-search' for s in sources)
    fetch=any(r.get('name')=='web_fetch' for r in completed) and any(s.get('backend')=='public-fetch' for s in sources)
    hosted_used=bool(state.get('hosted_calls',0))
    exact=result.get('text','').strip()=='Agentnik connected'
    ok=result.get('status')=='ok'
    evidence=exact if route=='chat' else (search and fetch if route=='managed' else hosted_used)
    markdown=cited_markdown(result.get('text',''),state)
    return {'outcome':'passed' if ok and evidence else 'failed' if not ok else 'completed_without_required_activity',
            'request_status':result.get('status','failed'),
            'failure_kind':state.get('failure',{}).get('kind'),
            'http_status':state.get('failure',{}).get('http_status'),
            'exact_chat_reply':exact if route=='chat' else None,
            'completed_tool_calls':len(completed),'managed_search_succeeded':search,'public_fetch_succeeded':fetch,
            'hosted_search_observed':hosted_used,'source_count':len(sources),
            'matched_citation_count':len(references & ids),'unmatched_citation_count':len(references-ids),
            'citation_links_generated':bool(sources and markdown!=result.get('text','')),
            'continuation_completed':bool(ok and completed and result.get('metrics',{}).get('model_requests',0)>1),
            'metrics':{k:v for k,v in result.get('metrics',{}).items() if (type(v) is bool or v is None or (type(v) in (int,float) and 0<=v<=2**63-1 and math.isfinite(v)))},
            'limitations':['headless check; no native UI validation','no claim for other models, protocols, accounts, or endpoints']}


def main(argv=None):
    p=parser();args=p.parse_args(argv)
    try:
        c={'url':core.base_url(args.url),'model':args.model,'protocol':args.protocol,'stream':not args.no_stream}
        if not args.model.strip(): raise ValueError('An explicit model alias is required')
        if args.route=='managed' and args.backend!='ollama': raise ValueError('Managed research requires --backend ollama')
        if args.route=='hosted' and not hosted.supported_endpoint(c): raise ValueError('Hosted research requires the official OpenAI Responses endpoint')
        if args.route!='managed' and (args.backend or args.search_key_file): raise ValueError('Search credentials/backend apply only to managed research')
        if args.execute and args.route=='managed' and not args.search_key_file: raise ValueError('Managed execution requires --search-key-file')
        if args.execute and args.output:
            if args.output.exists(): raise ValueError('Output already exists; choose a new report file')
            if any(args.output.resolve()==path.resolve() for path in (args.key_file,args.search_key_file) if path): raise ValueError('Report path must differ from key files')
            if not args.output.parent.is_dir(): raise ValueError('Report parent directory must already exist')
    except ValueError as exc: p.error(str(exc))
    limits=Limits(requests=3,rounds=3,calls=2,request_seconds=45,turn_seconds=120)
    prompt=CHAT_PROMPT if args.route=='chat' else WEB_PROMPT if args.route=='managed' else HOSTED_PROMPT
    plan={'execute':args.execute,'endpoint':core.endpoint(c),'model':c['model'],'protocol':c['protocol'],
          'route':args.route,'backend':args.backend,'prompt':prompt,'stream':c['stream'],
          'maximum_model_requests':1 if args.route in ('chat','hosted') else limits.requests,
          'maximum_tool_calls':limits.calls,'request_seconds':limits.request_seconds,'turn_seconds':limits.turn_seconds,
          'automatic_retries':False,'route_or_model_fallback':False,
          'data_flow':'model endpoint receives the prompt and tool results; managed search sends a query to Ollama and fetches public pages' if args.route=='managed' else 'selected model provider receives the prompt',
          'updates_application_settings':False}
    # Default planning never reads secrets, creates output, or contacts endpoints.
    if not args.execute:
        print(json.dumps(plan,indent=2));return 0
    keys=[]
    try:
        for path in (args.key_file,args.search_key_file):
            value=path.read_text(encoding='utf-8-sig').strip() if path else ''
            if path and (not value or any(ch.isspace() for ch in value)): raise ValueError('Key files must contain one nonempty token')
            keys.append(value)
    except (OSError,UnicodeError,ValueError):
        p.error('Cannot load supplied key file; check its path, access, and single-token format')
    c['api_key']=keys[0]
    print(json.dumps(research.scrub(plan,keys),indent=2),flush=True)
    cancel=threading.Event();runtime=Runtime(cancel,limits);previous=signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT,lambda *_:cancel.set())
    report={'schema_version':1,'timestamp':datetime.now(timezone.utc).isoformat(),'source':revision(),
            'endpoint':core.endpoint(c),'model':c['model'],'protocol':c['protocol'],'route':args.route,'backend':args.backend,'stream':c['stream']}
    try:
        messages=[{'role':'user','text':prompt}]
        if args.route=='chat':
            body=core.chat_body(c,messages)
            adapter=responses_tools if c['protocol']=='responses' else ollama_tools if core.native_ollama(c) else compat_tools
            state={}
            _,calls=runtime.wait(lambda:adapter.request(c,body,runtime,lambda _:None,state))
            if calls: raise ResearchError('Unrequested tool calls during chat check')
            result=dict(text=state.get('text',''),metrics=dict(state.get('metrics',{}),model_requests=1),status='ok')
        elif args.route=='managed':
            result=research.run_managed(c,messages,keys[1],lambda _:None,cancel,runtime=runtime)
        else:
            result=hosted.run_hosted(c,messages,'',lambda _:None,cancel,runtime=runtime)
        report.update(summarize(result,c,args.route))
    except Exception as exc:
        # Do not persist upstream messages, raw payloads, query URLs, or transcripts.
        report.update(outcome='cancelled' if cancel.is_set() else 'failed',error_type=type(exc).__name__,
                      http_status=exc.status if isinstance(exc,core.EndpointError) else None)
    finally:
        runtime.closed=True;signal.signal(signal.SIGINT,previous)
    if cancel.is_set(): report['outcome']='cancelled'
    report=research.scrub(report,keys)
    encoded=json.dumps(report,indent=2)+'\n'
    if args.output:
        try:
            with args.output.open('x',encoding='utf-8') as file:file.write(encoded)
        except OSError:
            print('Could not create the report file; sanitized result follows.',file=sys.stderr)
            print(encoded);return 1
    print(encoded)
    return 130 if report['outcome']=='cancelled' else 0 if report['outcome']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())

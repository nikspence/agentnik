"""Provider contracts and streaming transport; independent of the GUI."""
import base64
import json
import mimetypes
import math
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from . import tls

PROVIDERS = [
    ('OpenAI', 'responses', ('OPENAI_BASE_URL', 'OPENAI_API_BASE'), ('OPENAI_API_KEY',), 'https://api.openai.com/v1', 'OPENAI_MODEL'),
    ('Anthropic', 'messages', ('ANTHROPIC_BASE_URL',), ('ANTHROPIC_API_KEY',), 'https://api.anthropic.com/v1', 'ANTHROPIC_MODEL'),
    ('LiteLLM', 'chat', ('LITELLM_BASE_URL', 'LITELLM_API_BASE', 'LITELLM_URL'), ('LITELLM_API_KEY', 'LITELLM_MASTER_KEY'), '', 'LITELLM_MODEL'),
    ('Ollama', 'chat', ('OLLAMA_HOST', 'OLLAMA_BASE_URL'), ('OLLAMA_API_KEY',), 'http://localhost:11434/v1', 'OLLAMA_MODEL'),
    ('llama.cpp', 'chat', ('LLAMA_CPP_BASE_URL', 'LLAMA_CPP_URL', 'LLAMACPP_BASE_URL'), ('LLAMA_CPP_API_KEY', 'LLAMACPP_API_KEY'), '', 'LLAMA_CPP_MODEL'),
    *[(name, 'chat', (prefix+'_BASE_URL',), (prefix+'_API_KEY',), url, prefix+'_MODEL') for name, prefix, url in [
        ('OpenRouter', 'OPENROUTER', 'https://openrouter.ai/api/v1'), ('Groq', 'GROQ', 'https://api.groq.com/openai/v1'),
        ('Together', 'TOGETHER', 'https://api.together.xyz/v1'), ('Mistral', 'MISTRAL', 'https://api.mistral.ai/v1'),
        ('DeepSeek', 'DEEPSEEK', 'https://api.deepseek.com/v1'), ('xAI', 'XAI', 'https://api.x.ai/v1')]],
]
PROTOCOLS = ('responses', 'chat', 'messages')

def environment_host(url):
    """Use loopback when an environment URL specifies an IPv4 wildcard bind."""
    return re.sub(r'^(https?://)?0\.0\.0\.0(?=[:/?#]|$)',
                  lambda m:(m[1] or '')+'127.0.0.1',url.strip(),flags=re.IGNORECASE)


def environment_connections():
    first = lambda names: next((os.environ[n] for n in names if os.environ.get(n)), '')
    found = {}
    for name, protocol, urls, keys, default, model in PROVIDERS:
        url, key, mod = first(urls), first(keys), os.getenv(model, '')
        if url or key or mod:
            found['env:'+name] = dict(url=url or default, api_key=key, model=mod, protocol=protocol)
    key = first(('AWS_BEARER_TOKEN_BEDROCK', 'BEDROCK_API_KEY'))
    url = first(('BEDROCK_MANTLE_BASE_URL', 'BEDROCK_MANTLE_URL'))
    region = first(('AWS_REGION', 'AWS_DEFAULT_REGION'))
    if key or url:
        found['env:Bedrock Mantle'] = dict(url=url or (f'https://bedrock-mantle.{region}.api.aws/v1' if region else ''), api_key=key, model=os.getenv('BEDROCK_MODEL', ''), protocol='responses')
    for connection in found.values(): connection['url']=environment_host(connection['url'])
    return found

def base_url(url):
    url = url.strip().rstrip('/')
    if '://' not in url: url = 'http://' + url
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an HTTP(S) URL without credentials, query, or fragment.')
    for suffix in ('/chat/completions', '/responses', '/messages', '/systemone'):
        if url.endswith(suffix): url = url[:-len(suffix)]
    if not urllib.parse.urlsplit(url).path: url += '/v1'
    return url

def endpoint(c, mode='chat'):
    if mode == 'chat' and native_ollama(c): return base_url(c['url']).removesuffix('/v1')+'/api/chat'
    return base_url(c['url']) + ('/systemone' if mode == 'decision' else {'chat':'/chat/completions', 'responses':'/responses', 'messages':'/messages'}[c.get('protocol', 'chat')])

def direct_mantle(c):
    """Recognize only the direct AWS Mantle HTTPS authority, never gateways."""
    parsed=urllib.parse.urlsplit(base_url(c['url']))
    return (parsed.scheme=='https' and parsed.port in (None,443)
            and re.fullmatch(r'bedrock-mantle\.[a-z0-9-]+\.api\.aws',parsed.hostname or '') is not None)


def models_endpoint(c):
    base=base_url(c['url'])
    if direct_mantle(c):
        parsed=urllib.parse.urlsplit(base)
        return urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,'/v1/models','',''))
    return base+'/models'


def native_ollama(c):
    parsed = urllib.parse.urlsplit(base_url(c['url']))
    return c.get('protocol', 'chat') == 'chat' and (parsed.port == 11434 or parsed.hostname == 'ollama.com')

def headers(c):
    h = {'Content-Type':'application/json', 'Accept':'application/json'}
    if c.get('protocol') == 'messages':
        h['anthropic-version'] = '2023-06-01'
        if c.get('api_key'): h['x-api-key'] = c['api_key']
    elif c.get('api_key'): h['Authorization'] = 'Bearer '+c['api_key']
    return h

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        raise ValueError('Endpoint redirected the request. Use its final URL in the connection settings.')

class EndpointError(ValueError):
    """An explicit HTTP rejection, distinct from an uncertain transport failure."""
    def __init__(self,status,detail='',retry_after=None):
        self.status=status; self.detail=detail; self.retry_after=retry_after
        try: self.payload=json.loads(detail)
        except (ValueError,TypeError): self.payload={}
        super().__init__(f'HTTP {status}: {detail}')


def open_request(c, url, body=None, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers(c))
    try:
        handlers = [NoRedirect()]
        if tls.relaxed(): handlers.append(urllib.request.HTTPSHandler(context=tls.context()))
        return urllib.request.build_opener(*handlers).open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read(2048).decode('utf-8', 'replace')
        if c.get('api_key'): detail = detail.replace(c['api_key'], '[redacted]')
        raise EndpointError(e.code,detail,e.headers.get('Retry-After') if e.headers else None) from None

def get_json(c, url, timeout=10):
    with open_request(c, url, timeout=timeout) as r: return json.load(r)

def models(c):
    # The Mantle catalog uses OpenAI bearer authentication even for Messages connections.
    listing=dict(c,protocol='responses') if direct_mantle(c) else c
    data = get_json(listing, models_endpoint(c))
    return sorted(x['id'] for x in data.get('data', []) if isinstance(x, dict) and isinstance(x.get('id'), str))

def discover():
    found = {}
    for name, ports in [('Ollama', (11434,)), ('llama.cpp', (9931, 8080)), ('FastFlowLM', (52625,)), ('LiteLLM', (4000,))]:
        for port in ports:
            host = None
            for address in ('127.0.0.1', '::1'):
                try:
                    with socket.create_connection((address, port), timeout=.2): host = address
                    break
                except OSError: pass
            if host is None: continue
            url = f'http://[{host}]:{port}/v1' if ':' in host else f'http://{host}:{port}/v1'
            c = dict(url=url, protocol='chat', model='')
            status = 'open; unverified'
            try:
                available = models(c)
                status = 'compatible API'
                if available: c['model'] = available[0]
                if name == 'Ollama':
                    get_json(c, base_url(url).removesuffix('/v1')+'/api/version', 2)
                    status = 'Ollama confirmed'
            except Exception as e:
                if '401' in str(e) or '403' in str(e): status = 'authentication required'
            found[f'local:{name} :{port} ({status})'] = c
    return found

def discovery_identity(connection):
    """Compare discovered destinations without DNS requests or credential matching."""
    try:
        parsed=urllib.parse.urlsplit(base_url(connection['url']))
        host=parsed.hostname.lower().rstrip('.')
        if any(ch.isspace() for ch in host): return None
        if host=='localhost': host='127.0.0.1'
        return parsed.scheme.lower(),host,parsed.port or (443 if parsed.scheme=='https' else 80),parsed.path.rstrip('/')
    except (ValueError,KeyError,AttributeError): return None


def merge_discovered(environment,probed):
    """Keep stable environment names/settings, enriching them with matching probes."""
    result={name:dict(c) for name,c in environment.items()}
    for probe_name,probe in probed.items():
        identity=discovery_identity(probe)
        matches=[name for name,c in environment.items() if identity is not None and discovery_identity(c)==identity]
        if not matches:
            result[probe_name]=dict(probe); continue
        for name in matches:
            combined=dict(probe); combined.update(environment[name])
            if not combined.get('model'): combined['model']=probe.get('model','')
            combined['discovery_status']=probe_name
            result[name]=combined
    return result


def image_block(path, protocol, role='user'):
    mime = mimetypes.guess_type(path)[0]
    if mime not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
        raise ValueError('Use PNG, JPEG, WebP, or GIF images.')
    data = base64.b64encode(Path(path).read_bytes()).decode()
    if protocol == 'messages': return {'type':'image', 'source':{'type':'base64', 'media_type':mime, 'data':data}}
    if protocol == 'responses': return {'type':'input_image', 'image_url':f'data:{mime};base64,{data}'}
    return {'type':'image_url', 'image_url':{'url':f'data:{mime};base64,{data}'}}

def history_eligible(message):
    research=message.get('research',{})
    return (message.get('status','ok')=='ok'
            and research.get('status') in (None,'completed')
            and research.get('continuation_eligible',True) is True)


def chat_body(c, messages):
    protocol = c.get('protocol', 'chat')
    history = []; response_context_bytes=0
    for m in messages:
        if not history_eligible(m): continue
        if protocol=='responses' and m['role']=='assistant' and m.get('research',{}).get('response_items'):
            import copy
            saved=m['research']['response_items']
            response_context_bytes+=len(json.dumps(saved).encode())
            if response_context_bytes>128_000:
                raise ValueError('Saved Responses context exceeds 128 KB; open a new chat')
            history.extend(copy.deepcopy(saved)); continue
        if protocol in ('chat','messages') and not native_ollama(c) and m.get('research',{}).get('protocol')==protocol and m['research'].get('exchanges'):
            import copy
            saved=m['research']['exchanges']; response_context_bytes+=len(json.dumps(saved).encode())
            if response_context_bytes>128_000: raise ValueError('Saved tool context exceeds 128 KB; open a new chat')
            history.extend(copy.deepcopy(saved)); continue
        text_type = 'output_text' if m['role'] == 'assistant' else 'input_text'
        from .document_reader import message_text
        text = message_text(m)
        content = text
        if m.get('images'):
            content = [{'type':text_type if protocol == 'responses' else 'text', 'text':text}, *[image_block(p, protocol) for p in m['images']]]
        history.append({'role':m['role'], 'content':content})
    body = {'model':c['model'], 'input' if protocol == 'responses' else 'messages':history, 'stream':c.get('stream', True)}
    reasoning = c.get('reasoning')
    if native_ollama(c):
        from .ollama_tools import history_messages
        body['messages'] = history_messages(messages)
        if reasoning: body['think'] = False if reasoning.lower() == 'off' else reasoning
        if c.get('context_limit'): body['options'] = {'num_ctx':c['context_limit']}
        return body
    if protocol == 'messages':
        body['max_tokens'] = 8192
        if reasoning: body.update(thinking={'type':'adaptive'}, output_config={'effort':reasoning})
    elif reasoning:
        body.update({'reasoning':{'effort':reasoning}} if protocol == 'responses' else {'reasoning_effort':reasoning})
    if protocol == 'chat' and body['stream']: body['stream_options'] = {'include_usage':True}
    return body

def decision_body(c, form):
    state = form.get('state', '').strip()
    if not state:
        if not form.get('images'): raise ValueError('Enter state/context or attach an image.')
        state = 'Evaluate the attached images.'
    elif form.get('json_state'): state = json.loads(state)
    questions = {}
    for q in form['questions']:
        name = q['name'].strip()
        if not name or name in questions: raise ValueError('Question names must be nonempty and unique.')
        if not q['instructions'].strip(): raise ValueError('Every question needs instructions.')
        item = {'type':q['type'], 'instructions':q['instructions']}
        if q['type'] == 'choice':
            choices = q.get('choices', [])
            if not 2 <= len(choices) <= 26: raise ValueError('Choice questions need 2–26 options.')
            criteria = {}
            for label, desc in choices:
                if not label.strip() or label in criteria or not desc.strip(): raise ValueError('Choices need unique labels and descriptions.')
                criteria[label] = desc
            item['criteria'] = criteria
        elif q['type'] == 'score':
            levels = [x[1] for x in q.get('choices', [])]
            if not 2 <= len(levels) <= 10 or not all(x.strip() for x in levels): raise ValueError('Scores need 2–10 ordered level descriptions.')
            item['criteria'] = levels
        questions[name] = item
    if not questions: raise ValueError('Add at least one question.')
    body = {'model':c['model'], 'state':state, 'questions':questions}
    if form.get('images'):
        body['images'] = [base64.b64encode(Path(p).read_bytes()).decode() for p in form['images']]
    return body

TOKEN_METRICS = ('input_tokens','output_tokens','cached_input_tokens','cache_creation_input_tokens','reasoning_output_tokens')


def usage_snapshot(value):
    """Retain only known numeric counters; never persist arbitrary provider strings."""
    if not isinstance(value,dict): return {}
    scalar=('input_tokens','output_tokens','prompt_tokens','completion_tokens',
            'cache_read_input_tokens','cache_creation_input_tokens')
    nested={'input_tokens_details':('cached_tokens',), 'prompt_tokens_details':('cached_tokens',),
            'output_tokens_details':('reasoning_tokens',), 'completion_tokens_details':('reasoning_tokens',)}
    result={k:v for k,v in value.items() if k in scalar and type(v) in (int,float) and 0<=v<=2**63-1 and math.isfinite(v)}
    for name,fields in nested.items():
        if isinstance(value.get(name),dict):
            detail={k:v for k,v in value[name].items() if k in fields and type(v) in (int,float) and 0<=v<=2**63-1 and math.isfinite(v)}
            if detail: result[name]=detail
    return result


def merge_usage(previous, incoming):
    merged=usage_snapshot(previous)
    for key,value in usage_snapshot(incoming).items():
        if isinstance(value,dict): merged.setdefault(key,{}).update(value)
        else: merged[key]=value
    return merged


def usage_metrics(data):
    u = usage_snapshot(data.get('usage'))
    result = {}
    for dest, candidates in [('input_tokens', ('input_tokens', 'prompt_tokens')), ('output_tokens', ('output_tokens', 'completion_tokens'))]:
        for key in candidates:
            if key in u: result[dest] = u[key]; break
    # Messages reports uncached input separately from cache read/write tokens.
    # OpenAI detail counters are already included in input/output totals.
    if 'input_tokens' in u and any(k in u for k in ('cache_read_input_tokens','cache_creation_input_tokens')):
        result['input_tokens']=u['input_tokens']+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0)
    for source,dest in [('cache_read_input_tokens','cached_input_tokens'),('cache_creation_input_tokens','cache_creation_input_tokens')]:
        if source in u: result[dest]=u[source]
    for source,dest,field in [('input_tokens_details','cached_input_tokens','cached_tokens'),('prompt_tokens_details','cached_input_tokens','cached_tokens'),
                              ('output_tokens_details','reasoning_output_tokens','reasoning_tokens'),('completion_tokens_details','reasoning_output_tokens','reasoning_tokens')]:
        if field in u.get(source,{}): result[dest]=u[source][field]
    for key, dest in [('prompt_eval_count','input_tokens'), ('eval_count','output_tokens')]:
        if type(data.get(key)) in (int,float) and 0<=data[key]<=2**63-1 and math.isfinite(data[key]): result[dest] = data[key]
    for source, dest in [('prompt_eval_duration','prompt_seconds'), ('eval_duration','generation_seconds')]:
        if type(data.get(source)) in (int,float) and math.isfinite(data[source]) and data[source]>0: result[dest] = data[source]/1e9
    for key in ('prompt', 'generation'):
        tokens = result.get('input_tokens' if key == 'prompt' else 'output_tokens')
        if tokens is not None and result.get(key+'_seconds'): result[key+'_tps'] = tokens/result[key+'_seconds']
    return result


def total_token_rate(metrics):
    """End-to-end throughput; never substitute this for a generation-only rate."""
    incoming, outgoing, seconds = (metrics.get(k) for k in ('input_tokens','output_tokens','total_seconds'))
    if incoming is None or outgoing is None or seconds is None or seconds <= 0: return None
    return (incoming+outgoing)/seconds

def events(response):
    """SSE (including multiline data), JSON, and Ollama NDJSON."""
    ctype = response.headers.get('Content-Type', '')
    if 'text/event-stream' in ctype:
        pending = []
        for raw in response:
            line = raw.decode('utf-8').rstrip('\r\n')
            if not line:
                if pending:
                    value = '\n'.join(pending); pending = []
                    if value == '[DONE]': return
                    yield json.loads(value)
            elif line.startswith('data:'): pending.append(line[5:].lstrip())
        if pending and '\n'.join(pending) != '[DONE]': yield json.loads('\n'.join(pending))
    elif 'ndjson' in ctype:
        for line in response:
            if line.strip(): yield json.loads(line)
    else: yield json.load(response)

def run_request(c, mode, body, emit, cancel):
    start = time.monotonic(); metrics = {}; request_usage = {}; text = ''; thinking = ''
    thought_start = thought_end = None
    raw = None
    with open_request(c, endpoint(c, mode), body) as response:
        for data in events(response):
            if cancel.is_set(): raise InterruptedError('Request cancelled')
            if data.get('error'): raise ValueError(str(data['error']))
            raw = data; request_usage=merge_usage(request_usage,data.get('usage')); metrics.update(usage_metrics(dict(data,usage=request_usage)))
            if mode == 'decision': continue
            delta = ''; thought = ''
            if native_ollama(c):
                d = data.get('message', {}); delta = d.get('content',''); thought = d.get('thinking','')
            elif c.get('protocol') == 'responses':
                typ = data.get('type', '')
                if typ == 'response.output_text.delta': delta = data.get('delta', '')
                elif typ in ('response.reasoning_summary_text.delta', 'response.reasoning_text.delta'): thought = data.get('delta', '')
                elif typ in ('response.completed', 'response.incomplete', 'response.failed'):
                    metrics.update(usage_metrics(data.get('response', {})))
                    if typ != 'response.completed': raise ValueError('Response ended '+typ.split('.')[-1])
                elif 'output' in data:
                    delta = data.get('output_text') or ''.join(v.get('text', '') for o in data['output'] for v in o.get('content', []) if v.get('type') == 'output_text')
            elif c.get('protocol') == 'messages':
                typ = data.get('type')
                if typ == 'message_start':
                    request_usage=merge_usage(request_usage,data.get('message',{}).get('usage')); metrics.update(usage_metrics({'usage':request_usage}))
                elif typ == 'content_block_delta':
                    d = data.get('delta', {}); delta = d.get('text', ''); thought = d.get('thinking', '')
                elif isinstance(data.get('content'), list):
                    delta = ''.join(x.get('text', '') for x in data['content'] if x.get('type') == 'text')
                    thought = ''.join(x.get('thinking', '') for x in data['content'] if x.get('type') == 'thinking')
            else:
                choices = data.get('choices', [])
                if choices:
                    d = choices[0].get('delta') or choices[0].get('message') or {}
                    delta = d.get('content') or ''; thought = d.get('reasoning_content') or d.get('reasoning') or ''
            if not isinstance(delta, str): delta = ''.join(x.get('text', '') for x in delta)
            now = time.monotonic()
            if thought and thought_start is None: thought_start = now
            if delta and thought_start is not None and thought_end is None: thought_end = now
            text += delta; thinking += thought
            if delta or thought: emit({'text':text, 'thinking':thinking})
    if cancel.is_set(): raise InterruptedError('Request cancelled')
    metrics['total_seconds'] = time.monotonic()-start
    if mode == 'chat' and native_ollama(c) and urllib.parse.urlsplit(base_url(c['url'])).port == 11434:
        try:
            running = get_json(c,base_url(c['url']).removesuffix('/v1')+'/api/ps',timeout=2)
            for model in running.get('models',[]):
                if model.get('name') == c.get('model') or model.get('name') == c.get('model','')+':latest':
                    if isinstance(model.get('context_length'),int): metrics['context_limit'] = model['context_length']
                    break
        except Exception: pass  # Usage is still useful if server metadata is unavailable.
    # Stream arrival interval is an estimate, never reported as model compute time.
    if thought_start is not None: metrics['thinking_seconds_estimate'] = (thought_end or time.monotonic())-thought_start
    if mode == 'decision' and (not isinstance(raw, dict) or not isinstance(raw.get('answers'), dict)):
        raise ValueError('The endpoint did not return a System One answers object.')
    return {'text':text, 'thinking':thinking, 'metrics':metrics, 'raw':raw}

def validate_connections(data):
    if not isinstance(data, dict) or not isinstance(data.get('connections'), dict): raise ValueError('Expected a JSON object containing a connections mapping.')
    result = {}
    for name, c in data['connections'].items():
        if not isinstance(name, str) or not name.strip() or not isinstance(c, dict): raise ValueError('Invalid connection name or value.')
        clean = {k:v for k,v in c.items() if k in ('url','protocol','model','reasoning','api_key','context_limit','stream')}
        if not isinstance(clean.get('url'), str): raise ValueError(f'{name}: URL required')
        base_url(clean['url'])
        if clean.get('protocol', 'chat') not in PROTOCOLS: raise ValueError(f'{name}: invalid protocol')
        for field in ('api_key','model','reasoning'):
            if field in clean and not isinstance(clean[field], str): raise ValueError(f'{name}: {field} must be text')
        if 'stream' in clean and not isinstance(clean['stream'], bool): raise ValueError('stream must be true or false')
        if 'context_limit' in clean and (type(clean['context_limit']) is not int or clean['context_limit'] < 0): raise ValueError('Context limit must be a nonnegative integer')
        result[name] = clean
    return result

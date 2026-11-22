"""MCP server configuration and bounded initialization preview."""
import json
import hashlib
import math
import os
import re
import unicodedata
from pathlib import PurePosixPath,PureWindowsPath
from urllib.parse import urlsplit

PROTOCOL='2025-11-25'
MAX_OUTPUT=65536
MAX_DISCOVERY_OUTPUT=131072
MAX_TOOL_RESULT_OUTPUT=1048576
MAX_RESOURCE_RESULT_OUTPUT=16*1024*1024

def response_limit(phase):
    return MAX_DISCOVERY_OUTPUT if phase=='tools' else MAX_RESOURCE_RESULT_OUTPUT if phase=='resource_read' else MAX_TOOL_RESULT_OUTPUT if phase in ('call','task_result','modern_task_poll','prompt_get') else MAX_OUTPUT
DEFAULT_TIMEOUT_SECONDS=60
MAX_TIMEOUT_SECONDS=900


class MCPListChangedError(ValueError):
    """A server changed a catalog that must remain stable for an operation."""


def server_log_notice(message):
    """Summarize actionable server logs; never serialize arbitrary structured data."""
    if not isinstance(message,dict) or message.get('method')!='notifications/message' or 'id' in message:return None
    params=message.get('params')
    if not isinstance(params,dict) or params.get('level') not in ('warning','error','critical','alert','emergency') or 'data' not in params:return None
    value=params['data']
    text=' '.join(''.join(ch if ch.isprintable() else ' ' for ch in value[:1000]).split())[:240] if isinstance(value,str) else ''
    return 'MCP server '+params['level']+(': '+text if text else ' (details omitted)')+' [untrusted server message]'


def task_status_notice(message,task_id,previous):
    """Describe an active task's status without displaying server-supplied text."""
    if not task_id or not isinstance(message,dict) or message.get('method')!='notifications/tasks/status' or 'id' in message:return None
    params=message.get('params')
    if not isinstance(params,dict) or params.get('taskId')!=task_id:return None
    status=params.get('status')
    if status not in ('working','input_required','completed','failed','cancelled') or status==previous:return None
    suffix='; task input is not supported by Agentnik.' if status=='input_required' else '.'
    return status,'MCP task '+task_id+' status: '+status+suffix


def invalidate_server_list(session,method):
    """Invalidate only the changed catalog, rejecting affected in-flight work."""
    if method=='notifications/tools/list_changed':
        raise MCPListChangedError('MCP tools changed; reconnect before making another call.')
    if method=='notifications/resources/list_changed':
        session.resource_items=[];session.template_items=[]
        if session.phase in ('resource_list','template_list') or session.phase=='completion' and getattr(session,'completion_kind',None)=='resource':
            raise MCPListChangedError('MCP resources changed during discovery; reconnect and list them again.')
        return 'MCP resources changed; list them again before reading.'
    if method=='notifications/prompts/list_changed':
        session.prompt_items=[]
        if session.phase in ('prompt_list','prompt_get') or session.phase=='completion' and getattr(session,'completion_kind',None)=='prompt':
            raise MCPListChangedError('MCP prompts changed during retrieval; reconnect and list them again.')
        return 'MCP prompts changed; list them again before retrieval.'
    return ''

def progress_notice(message,token,previous):
    """Validate a progress notification against the active tool call."""
    if not isinstance(message,dict) or message.get('method')!='notifications/progress' or 'id' in message:return None
    params=message.get('params')
    if not isinstance(params,dict) or params.get('progressToken')!=token:return None
    value=params.get('progress');total=params.get('total');description=params.get('message','')
    def valid_number(number):return type(number) in (int,float) and abs(number)<=10**100 and math.isfinite(number) and number>=0
    if not valid_number(value) or (previous is not None and value<=previous):return None
    if total is not None and not valid_number(total):return None
    if not isinstance(description,str):return None
    description=' '.join(''.join(ch if ch.isprintable() else ' ' for ch in description).split())[:240]
    detail='Progress '+format(value,'.6g')+(' / '+format(total,'.6g') if total is not None else '')+(': '+description if description else '')
    return value,detail

PARALLEL_MCP_TOOLS=frozenset(('web_search','web_fetch','web_decisions','web_research','find_verticals','search_vertical'))

def safe_parallel_tool_query(parts):
    """Allow Parallel's documented non-secret tool selector, not arbitrary URL queries."""
    if parts.hostname!='mcp.parallel.ai' or parts.port not in (None,443) or parts.path!='/mcp':return False
    if not parts.query.startswith('tools='):return False
    names=parts.query[len('tools='):].split(',')
    return bool(names) and len(names)==len(set(names)) and all(name in PARALLEL_MCP_TOOLS for name in names)


def server_timeout(server):
    value=server.get('timeout_seconds',DEFAULT_TIMEOUT_SECONDS)
    if type(value) is not int or not 1<=value<=MAX_TIMEOUT_SECONDS:raise ValueError('Invalid MCP timeout')
    return value


def validate_servers(servers):
    if not isinstance(servers,list) or len(servers)>20:raise ValueError('MCP servers must be a list of at most 20 entries')
    names=set()
    for server in servers:
        if not isinstance(server,dict):raise ValueError('Invalid MCP server configuration')
        remote=server.get('transport')=='http'
        required=({'name','transport','url','credential_id','enabled'} if remote else {'name','command','args','enabled'})
        if not required.issubset(server) or set(server)-required-({'env','timeout_seconds','working_directory'} if not remote else {'timeout_seconds','auth_type'}):raise ValueError('Invalid MCP server configuration')
        server_timeout(server)
        name=server['name']
        if not isinstance(name,str) or not name.strip() or len(name)>80 or name.casefold() in names:raise ValueError('MCP server names must be unique and nonempty')
        names.add(name.casefold())
        if remote:
            url=server['url'];credential=server['credential_id']
            if not isinstance(url,str) or len(url)>2048 or any(ord(c)<33 or ord(c)==127 for c in url):raise ValueError('Invalid MCP URL')
            try:parts=urlsplit(url);port=parts.port
            except ValueError:raise ValueError('Invalid MCP URL') from None
            if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.fragment or (parts.query and not safe_parallel_tool_query(parts)):raise ValueError('MCP URL must use HTTPS without credentials or a fragment; only the documented Parallel tool selector query is supported')
            if not isinstance(credential,str) or len(credential)>128:raise ValueError('Invalid MCP credential reference')
            if 'auth_type' in server and (server['auth_type']!='oauth' or not credential):raise ValueError('Invalid MCP authentication type')
        else:
            command=server['command'];args=server['args']
            if not isinstance(command,str) or not command.strip() or len(command)>1024 or '\x00' in command:raise ValueError('Invalid MCP executable')
            if not isinstance(args,list) or len(args)>32 or any(not isinstance(arg,str) or len(arg)>2048 or '\x00' in arg for arg in args):raise ValueError('Invalid MCP argument list')
            directory=server.get('working_directory','')
            if not isinstance(directory,str) or len(directory)>2048 or any(ord(ch)<32 or ord(ch)==127 for ch in directory) or (directory and not (PurePosixPath(directory).is_absolute() or PureWindowsPath(directory).is_absolute())):raise ValueError('Invalid MCP working directory; use an absolute path')
            validate_environment_references(server.get('env',{}))
        if type(server['enabled']) is not bool:raise ValueError('Invalid MCP enabled state')
    return servers


def server_fingerprint(server):
    """Bind a remembered selection to its exact saved configuration without saving it twice."""
    validate_servers([server])
    payload=json.dumps(server,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode('ascii')
    return hashlib.sha256(payload).hexdigest()


def validate_environment_references(mapping):
    """Allow variable names only; values must never appear in configuration."""
    if not isinstance(mapping,dict) or len(mapping)>32:raise ValueError('Invalid MCP environment mappings')
    names=set()
    for target,source in mapping.items():
        if not isinstance(target,str) or not isinstance(source,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',target) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',source) or target.casefold() in names:raise ValueError('Invalid MCP environment variable name')
        names.add(target.casefold())
    return mapping


def resolve_environment_references(mapping):
    validate_environment_references(mapping);values={}
    for target,source in mapping.items():
        value=os.environ.get(source)
        if value is None or not value or len(value)>8192 or '\x00' in value:raise ValueError('An MCP environment variable is missing or invalid.')
        values[target]=value
    return values


def rpc_error(message):
    """Return bounded, untrusted JSON-RPC error text; never expose error data."""
    if not isinstance(message,dict) or 'result' in message:raise ValueError('Invalid MCP error response')
    error=message.get('error')
    if not isinstance(error,dict) or type(error.get('code')) is not int or not -(2**31)<=error['code']<2**31 or not isinstance(error.get('message'),str):raise ValueError('Invalid MCP error response')
    text=''.join(' ' if unicodedata.category(ch).startswith('C') else ch for ch in error['message'][:512]).strip()
    return 'MCP server error ('+str(error['code'])+'): '+(text or 'No details provided')+' [untrusted server message]'


def initialize_request(elicitation=False):
    capabilities={'tasks':{}}
    if elicitation:capabilities['elicitation']={'form':{},'url':{}}
    return {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':PROTOCOL,'capabilities':capabilities,'clientInfo':{'name':'Agentnik','version':'0.1'}}}


def created_task_id(result):
    """Validate a task creation response without interpreting its opaque ID."""
    task=result.get('task') if isinstance(result,dict) else None
    if not isinstance(task,dict):raise ValueError('Invalid MCP task creation response')
    ident=task.get('taskId')
    if not isinstance(ident,str) or not ident or len(ident)>256 or any(ord(ch)<32 or ord(ch)==127 for ch in ident) or task.get('status')!='working':raise ValueError('Invalid MCP task identity or status')
    for name in ('createdAt','lastUpdatedAt'):
        if not isinstance(task.get(name),str) or not 1<=len(task[name])<=80:raise ValueError('Invalid MCP task timestamp')
    ttl=task.get('ttl')
    if 'ttl' not in task or (ttl is not None and (type(ttl) not in (int,float) or abs(ttl)>10**100 or not math.isfinite(ttl) or ttl<0)):raise ValueError('Invalid MCP task lifetime')
    return ident


def validate_task_result(result,ident):
    meta=result.get('_meta') if isinstance(result,dict) else None
    related=meta.get('io.modelcontextprotocol/related-task') if isinstance(meta,dict) else None
    if not isinstance(related,dict) or related.get('taskId')!=ident:raise ValueError('MCP task result identity mismatch')


def task_cleanup_text(result):
    """Describe a task's asynchronous cleanup without claiming uncertain success."""
    if isinstance(result,dict) and isinstance(result.get('server'),str) and type(result.get('modern_task_cancel_ack')) is bool:
        server=''.join(ch if ch.isprintable() else ' ' for ch in result['server'])[:80]
        detail='cancellation request acknowledged' if result['modern_task_cancel_ack'] else 'cancellation request was not acknowledged'
        return 'MCP task on '+server+': '+detail+'; the task may still be running.'
    if not isinstance(result,dict) or not isinstance(result.get('server'),str) or not isinstance(result.get('task_id'),str) or (result.get('task_cancelled') is not None and type(result['task_cancelled']) is not bool):raise ValueError('Invalid MCP task cleanup result')
    server=''.join(ch if ch.isprintable() else ' ' for ch in result['server'])[:80];ident=''.join(ch if ch.isprintable() else ' ' for ch in result['task_id'])[:256];status=result.get('task_cancelled')
    detail='cancellation confirmed' if status is True else 'cancellation was not confirmed; the task may still be running' if status is False else 'cancellation was not requested; the task may still be running'
    return 'MCP task '+ident+' on '+server+': '+detail+'.'


def parse_initialize(line, supported_protocols=(PROTOCOL,)):
    try:message=json.loads(line)
    except (ValueError,UnicodeError,RecursionError):raise ValueError('Invalid MCP initialization response') from None
    if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or type(message.get('id')) is not int or message['id']!=1 or not isinstance(message.get('result'),dict):raise ValueError('Invalid MCP initialization response')
    result=message['result'];info=result.get('serverInfo');capabilities=result.get('capabilities')
    if result.get('protocolVersion') not in supported_protocols:raise ValueError('Server did not accept a supported MCP protocol version')
    if not isinstance(info,dict) or not isinstance(info.get('name'),str) or not info['name'] or len(info['name'])>256 or not isinstance(info.get('version'),str) or len(info['version'])>256 or not isinstance(capabilities,dict):raise ValueError('Invalid MCP server identity or capabilities')
    names=[name for name in ('tools','resources','prompts','logging','completions') if name in capabilities and isinstance(capabilities[name],dict)]
    tasks=capabilities.get('tasks') if result['protocolVersion']==PROTOCOL else None
    task_capabilities={'tool_calls':False,'list':False,'cancel':False}
    if isinstance(tasks,dict):
        names.append('tasks')
        requests=tasks.get('requests');tools=requests.get('tools') if isinstance(requests,dict) else None
        task_capabilities={'tool_calls':isinstance(tools,dict) and isinstance(tools.get('call'),dict),
                           'list':isinstance(tasks.get('list'),dict),'cancel':isinstance(tasks.get('cancel'),dict)}
    return {'name':info['name'],'version':info['version'] or 'unknown','protocol':result['protocolVersion'],'capabilities':names,'task_capabilities':task_capabilities}

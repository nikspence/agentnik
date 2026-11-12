"""MCP server configuration and bounded initialization preview."""
import json
import hashlib
import os
import re
import unicodedata
from pathlib import PurePosixPath,PureWindowsPath
from urllib.parse import urlsplit

PROTOCOL='2025-11-25'
MAX_OUTPUT=65536
DEFAULT_TIMEOUT_SECONDS=60
MAX_TIMEOUT_SECONDS=900
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
        if not required.issubset(server) or set(server)-required-({'env','timeout_seconds','working_directory'} if not remote else {'timeout_seconds'}):raise ValueError('Invalid MCP server configuration')
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


def initialize_request():
    return {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':PROTOCOL,'capabilities':{},'clientInfo':{'name':'Agentnik','version':'0.1'}}}


def parse_initialize(line, supported_protocols=(PROTOCOL,)):
    try:message=json.loads(line)
    except (ValueError,UnicodeError,RecursionError):raise ValueError('Invalid MCP initialization response') from None
    if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or type(message.get('id')) is not int or message['id']!=1 or not isinstance(message.get('result'),dict):raise ValueError('Invalid MCP initialization response')
    result=message['result'];info=result.get('serverInfo');capabilities=result.get('capabilities')
    if result.get('protocolVersion') not in supported_protocols:raise ValueError('Server did not accept a supported MCP protocol version')
    if not isinstance(info,dict) or not isinstance(info.get('name'),str) or not info['name'] or len(info['name'])>256 or not isinstance(info.get('version'),str) or len(info['version'])>256 or not isinstance(capabilities,dict):raise ValueError('Invalid MCP server identity or capabilities')
    return {'name':info['name'],'version':info['version'] or 'unknown','protocol':result['protocolVersion'],'capabilities':[name for name in ('tools','resources','prompts','logging','completions') if name in capabilities and isinstance(capabilities[name],dict)]}

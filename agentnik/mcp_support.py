"""MCP server configuration and bounded initialization preview."""
import json
import os
import re
from urllib.parse import urlsplit

PROTOCOL='2025-11-25'
MAX_OUTPUT=65536


def validate_servers(servers):
    if not isinstance(servers,list) or len(servers)>20:raise ValueError('MCP servers must be a list of at most 20 entries')
    names=set()
    for server in servers:
        if not isinstance(server,dict):raise ValueError('Invalid MCP server configuration')
        remote=server.get('transport')=='http'
        required=({'name','transport','url','credential_id','enabled'} if remote else {'name','command','args','enabled'})
        if not required.issubset(server) or set(server)-required-({'env'} if not remote else set()):raise ValueError('Invalid MCP server configuration')
        name=server['name']
        if not isinstance(name,str) or not name.strip() or len(name)>80 or name.casefold() in names:raise ValueError('MCP server names must be unique and nonempty')
        names.add(name.casefold())
        if remote:
            url=server['url'];credential=server['credential_id']
            if not isinstance(url,str) or len(url)>2048 or any(ord(c)<33 or ord(c)==127 for c in url):raise ValueError('Invalid MCP URL')
            try:parts=urlsplit(url);port=parts.port
            except ValueError:raise ValueError('Invalid MCP URL') from None
            if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.fragment or parts.query:raise ValueError('MCP URL must use HTTPS without credentials, a query, or a fragment')
            if not isinstance(credential,str) or len(credential)>128:raise ValueError('Invalid MCP credential reference')
        else:
            command=server['command'];args=server['args']
            if not isinstance(command,str) or not command.strip() or len(command)>1024 or '\x00' in command:raise ValueError('Invalid MCP executable')
            if not isinstance(args,list) or len(args)>32 or any(not isinstance(arg,str) or len(arg)>2048 or '\x00' in arg for arg in args):raise ValueError('Invalid MCP argument list')
            validate_environment_references(server.get('env',{}))
        if type(server['enabled']) is not bool:raise ValueError('Invalid MCP enabled state')
    return servers


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

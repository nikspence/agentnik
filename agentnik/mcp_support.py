"""Explicit, local-only MCP server configuration and initialization preview."""
import json

PROTOCOL='2025-11-25'
MAX_OUTPUT=65536


def validate_servers(servers):
    if not isinstance(servers,list) or len(servers)>20:raise ValueError('MCP servers must be a list of at most 20 entries')
    names=set()
    for server in servers:
        if not isinstance(server,dict) or set(server)!={'name','command','args','enabled'}:raise ValueError('Invalid MCP server configuration')
        name=server['name'];command=server['command'];args=server['args']
        if not isinstance(name,str) or not name.strip() or len(name)>80 or name.casefold() in names:raise ValueError('MCP server names must be unique and nonempty')
        names.add(name.casefold())
        if not isinstance(command,str) or not command.strip() or len(command)>1024 or '\x00' in command:raise ValueError('Invalid MCP executable')
        if not isinstance(args,list) or len(args)>32 or any(not isinstance(arg,str) or len(arg)>2048 or '\x00' in arg for arg in args):raise ValueError('Invalid MCP argument list')
        if type(server['enabled']) is not bool:raise ValueError('Invalid MCP enabled state')
    return servers


def initialize_request():
    return {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':PROTOCOL,'capabilities':{},'clientInfo':{'name':'Agentnik','version':'0.1'}}}


def parse_initialize(line):
    try:message=json.loads(line)
    except (ValueError,UnicodeError,RecursionError):raise ValueError('Invalid MCP initialization response') from None
    if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or type(message.get('id')) is not int or message['id']!=1 or not isinstance(message.get('result'),dict):raise ValueError('Invalid MCP initialization response')
    result=message['result'];info=result.get('serverInfo');capabilities=result.get('capabilities')
    if result.get('protocolVersion')!=PROTOCOL:raise ValueError('Server did not accept the supported MCP protocol version')
    if not isinstance(info,dict) or any(not isinstance(info.get(k),str) or not info[k] or len(info[k])>256 for k in ('name','version')) or not isinstance(capabilities,dict):raise ValueError('Invalid MCP server identity or capabilities')
    return {'name':info['name'],'version':info['version'],'protocol':PROTOCOL,'capabilities':[name for name in ('tools','resources','prompts','logging','completions') if name in capabilities and isinstance(capabilities[name],dict)]}

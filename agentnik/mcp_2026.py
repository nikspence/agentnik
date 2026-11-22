"""MCP 2026-07-28 request metadata and HTTP routing header construction."""
import base64
import re

PROTOCOL='2026-07-28'
_TOKEN=re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_PREFIX='=?base64?'
_SUFFIX='?='
_SAFE_INTEGER=2**53-1
INPUT_REQUIRED_ERROR='The MCP server requested interactive input, which Agentnik cannot provide yet. The request was not continued.'
# These errors can indicate that a stateless server rejected the legacy
# initialization envelope. Discovery is read-only and occurs only at startup.
LEGACY_ENVELOPE_ERRORS=frozenset((-32600,-32601,-32602,-32020,-32022))


def parse_discovery(result):
    versions=result.get('supportedVersions') if isinstance(result,dict) else None
    capabilities=result.get('capabilities') if isinstance(result,dict) else None
    if not isinstance(versions,list) or PROTOCOL not in versions or any(not isinstance(version,str) for version in versions) or not isinstance(capabilities,dict) or result.get('resultType','complete')!='complete':raise ValueError('Invalid MCP discovery response')
    meta=result.get('_meta');info=meta.get('io.modelcontextprotocol/serverInfo') if isinstance(meta,dict) else None
    valid=(isinstance(info,dict) and isinstance(info.get('name'),str) and bool(info['name']) and len(info['name'])<=256 and isinstance(info.get('version'),str) and len(info['version'])<=256 and all(ch.isprintable() for ch in info['name']+info['version']))
    filters={field:True for capability,field in (('tools','toolsListChanged'),('resources','resourcesListChanged'),('prompts','promptsListChanged')) if isinstance(capabilities.get(capability),dict) and capabilities[capability].get('listChanged') is True}
    extensions=capabilities.get('extensions');task_extension=isinstance(extensions,dict) and isinstance(extensions.get('io.modelcontextprotocol/tasks'),dict)
    return {'name':info['name'] if valid else 'MCP server','version':(info['version'] or 'unknown') if valid else 'unknown','server_identity_reported':valid,'protocol':PROTOCOL,'capabilities':[name for name in ('tools','resources','prompts','logging','completions') if isinstance(capabilities.get(name),dict)],'subscription_filters':filters,'task_capabilities':{'tool_calls':False,'list':False,'cancel':False},'task_extension_advertised':task_extension}


def header_value(value):
    """Encode a routing value without allowing HTTP header injection."""
    if type(value) is bool:value='true' if value else 'false'
    elif type(value) is int:
        if not -_SAFE_INTEGER<=value<=_SAFE_INTEGER:raise ValueError('MCP header integer is out of range')
        value=str(value)
    elif not isinstance(value,str):raise ValueError('Invalid MCP header value')
    raw=value.encode('utf-8')
    if (not value or value!=value.strip(' \t') or any(ord(ch)!=9 and not 32<=ord(ch)<=126 for ch in value)
            or value.startswith(_PREFIX) and value.endswith(_SUFFIX)):
        return _PREFIX+base64.b64encode(raw).decode('ascii')+_SUFFIX
    return value


def header_fields(schema):
    """Validate all custom header annotations and return exact argument paths."""
    if not isinstance(schema,dict):raise ValueError('Invalid MCP input schema')
    found=[];names=set();visited=0
    def walk(node,path,reachable,property_node=False):
        nonlocal visited
        visited+=1
        if visited>10000 or len(path)>64:raise ValueError('MCP input schema is too complex')
        if isinstance(node,list):
            for item in node:walk(item,path,False)
        elif isinstance(node,dict):
            if 'x-mcp-header' in node:
                name=node['x-mcp-header'];kind=node.get('type')
                if not reachable or not property_node or not isinstance(name,str) or not _TOKEN.fullmatch(name) or len(name)>128 or kind not in ('string','integer','boolean') or name.lower() in names:raise ValueError('Invalid MCP custom header annotation')
                names.add(name.lower());found.append((name,path,kind))
            for key,value in node.items():
                if key=='x-mcp-header':continue
                if key=='properties' and reachable and isinstance(value,dict):
                    for name,subschema in value.items():
                        if not isinstance(name,str):raise ValueError('Invalid MCP property name')
                        walk(subschema,path+(name,),True,True)
                else:walk(value,path,False)
    walk(schema,(),True)
    return found


def prepare_request(message,schema=None,client_capabilities=None):
    """Return a self-describing JSON-RPC request and its matching HTTP headers."""
    if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or type(message.get('id')) is not int:raise ValueError('Invalid MCP request')
    method=message.get('method');params=message.get('params',{})
    if not isinstance(method,str) or not method or any(not 33<=ord(ch)<=126 for ch in method) or not isinstance(params,dict):raise ValueError('Invalid MCP request')
    meta=params.get('_meta',{})
    if not isinstance(meta,dict):raise ValueError('Invalid MCP request metadata')
    meta=dict(meta,**{'io.modelcontextprotocol/protocolVersion':PROTOCOL,'io.modelcontextprotocol/clientInfo':{'name':'Agentnik','version':'0.1'},'io.modelcontextprotocol/clientCapabilities':dict(client_capabilities or {})})
    params=dict(params,_meta=meta);request=dict(message,params=params)
    headers={'MCP-Protocol-Version':PROTOCOL,'Mcp-Method':method}
    field={'tools/call':'name','prompts/get':'name','resources/read':'uri','tasks/get':'taskId','tasks/update':'taskId','tasks/cancel':'taskId'}.get(method)
    if field:
        value=params.get(field)
        if not isinstance(value,str) or not value:raise ValueError('Missing MCP routing name')
        headers['Mcp-Name']=header_value(value)
    if method=='tools/call' and schema is not None:
        arguments=params.get('arguments',{})
        if not isinstance(arguments,dict):raise ValueError('Invalid MCP tool arguments')
        for name,path,kind in header_fields(schema):
            value=arguments
            for part in path:
                if not isinstance(value,dict) or part not in value:value=None;break
                value=value[part]
            if value is None:continue
            if (kind=='string' and not isinstance(value,str)) or (kind=='integer' and type(value) is not int) or (kind=='boolean' and type(value) is not bool):raise ValueError('Invalid MCP custom header argument')
            headers['Mcp-Param-'+name]=header_value(value)
    return request,headers

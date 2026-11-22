"""Optional in-process interoperability check with MCP Python SDK 2.x."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from agentnik.mcp_2026 import PROTOCOL,prepare_request


def main():
    from mcp.server.mcpserver import MCPServer
    from starlette.testclient import TestClient
    from pydantic import Field
    from typing import Annotated
    server=MCPServer('Agentnik wire smoke',version='1')

    @server.tool()
    def add(a:int,b:int)->int:
        """Add two synthetic integers."""
        return a+b

    @server.tool()
    def echo(region:Annotated[str,Field(json_schema_extra={'x-mcp-header':'Region'})])->str:
        """Return a synthetic region."""
        return region

    app=server.streamable_http_app(stateless_http=True,json_response=True)
    with TestClient(app,base_url='http://127.0.0.1:8000') as client:
        def send(method,ident,params,schema=None):
            body,headers=prepare_request({'jsonrpc':'2.0','id':ident,'method':method,'params':params},schema)
            headers['Accept']='application/json, text/event-stream'
            response=client.post('/mcp',json=body,headers=headers)
            response.raise_for_status();result=response.json()
            if 'error' in result:raise RuntimeError('SDK rejected '+method)
            return result['result']
        discovery=send('server/discover',1,{})
        if PROTOCOL not in discovery['supportedVersions']:raise RuntimeError('SDK does not support requested protocol')
        tools=send('tools/list',2,{})['tools']
        if not any(tool['name']=='add' for tool in tools):raise RuntimeError('SDK omitted synthetic tool')
        result=send('tools/call',3,{'name':'add','arguments':{'a':2,'b':3}})
        if result.get('isError') or '5' not in json.dumps(result):raise RuntimeError('SDK tool call failed')
        echo_tool=next(tool for tool in tools if tool['name']=='echo')
        if echo_tool['inputSchema']['properties']['region'].get('x-mcp-header')!='Region':raise RuntimeError('SDK omitted header annotation')
        result=send('tools/call',4,{'name':'echo','arguments':{'region':'한글'}},echo_tool['inputSchema'])
        if result.get('isError') or '한글' not in json.dumps(result,ensure_ascii=False):raise RuntimeError('SDK header-routing call failed')
    print(json.dumps({'protocol':PROTOCOL,'checks':['discovery','tool listing','tool call','encoded parameter header'],'transport':'in-process SDK HTTP'}))


if __name__=='__main__':main()

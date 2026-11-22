"""Optional offline interoperability smoke test against the installed MCP Python SDK.

Run explicitly with an environment containing MCP Python SDK 2.x and PySide6.
The test starts its own stdio server and uses only synthetic, in-memory data.
"""
import json
import sys
from importlib.metadata import version
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def serve():
    from mcp.server.mcpserver import MCPServer
    from typing import TypedDict
    class Addition(TypedDict):
        sum:int
    server=MCPServer('Agentnik smoke',version='1')

    @server.tool(structured_output=True)
    def add(a:int,b:int)->Addition:
        """Add two synthetic integers."""
        return {'sum':a+b}

    @server.resource('smoke://fixture')
    def fixture()->str:
        return 'Synthetic resource'

    @server.resource('smoke://items/{item}')
    def item_resource(item:str)->str:
        return 'Synthetic item '+item

    @server.prompt()
    def greet(name:str)->str:
        return 'Hello '+name

    server.run(transport='stdio')


def run():
    from PySide6.QtCore import QCoreApplication,QEventLoop,QTimer
    from agentnik.mcp_local import LocalSession
    from agentnik.mcp_schema import validate_tool_arguments,validate_tool_result
    app=QCoreApplication.instance() or QCoreApplication([])
    session=LocalSession(sys.executable,[str(Path(__file__).resolve()),'--server'],timeout_seconds=15)
    loop=QEventLoop();result={'step':'discover'};timer=QTimer();timer.setSingleShot(True)

    def fail(message):
        result['error']=str(message);loop.quit()

    def discovered(info):
        try:
            tool=next(item for item in info['tool_details'] if item['name']=='add')
            if tool.get('output_schema_status')!='available':raise RuntimeError('Output schema was not discovered')
            validate_tool_arguments(tool['schema'],{'a':2,'b':3});result['tool']=tool
            result['protocol']=info['protocol'];result['step']='call'
            if not session.call(tool,{'a':2,'b':3}):raise RuntimeError('Tool call was rejected')
        except Exception as exc:fail(exc)

    def called(message):
        try:
            if 'error' in message:raise RuntimeError(message['error'])
            output=message['call_result'];validate_tool_result(result['tool'],output)
            if output.get('structuredContent',{}).get('sum')!=5:raise RuntimeError('Unexpected synthetic tool result: '+json.dumps(output))
            result['step']='resources'
            if not session.list_resources():raise RuntimeError('Resource listing was rejected')
        except Exception as exc:fail(exc)

    def resources(message):
        try:
            if 'error' in message:raise RuntimeError(message['error'])
            if result['step']=='resources':
                uri=next(item['uri'] for item in message['resources'] if item['uri']=='smoke://fixture')
                result['step']='read'
                if not session.read_resource(uri):raise RuntimeError('Resource read was rejected')
            elif result['step']=='read':
                if message['contents'][0]['text']!='Synthetic resource':raise RuntimeError('Unexpected resource contents')
                result['step']='templates'
                if not session.list_resource_templates():raise RuntimeError('Template listing was rejected')
            elif result['step']=='templates':
                template=next(item for item in message['templates'] if item['uriTemplate']=='smoke://items/{item}')
                result['step']='template_read'
                if not session.read_resource_template(template,{'item':'alpha'},'smoke://items/alpha'):raise RuntimeError('Template read was rejected')
            else:
                if message['contents'][0]['text']!='Synthetic item alpha':raise RuntimeError('Unexpected template contents')
                result['step']='prompts'
                if not session.list_prompts():raise RuntimeError('Prompt listing was rejected')
        except Exception as exc:fail(exc)

    def prompts(message):
        try:
            if 'error' in message:raise RuntimeError(message['error'])
            if result['step']=='prompts':
                prompt=next(item for item in message['prompts'] if item['name']=='greet');result['step']='prompt_get'
                if not session.list_prompts({'prompt':prompt,'arguments':{'name':'world'}}):raise RuntimeError('Prompt retrieval was rejected')
            else:
                if message['messages'][0]['content']['text']!='Hello world':raise RuntimeError('Unexpected prompt content')
                result['step']='complete';loop.quit()
        except Exception as exc:fail(exc)

    session.discovered.connect(discovered);session.called.connect(called);session.resources.connect(resources);session.prompts.connect(prompts)
    session.ended.connect(lambda message:fail(message.get('error','Server exited')) if result['step']!='complete' else None)
    timer.timeout.connect(lambda:fail('Smoke test timed out'));timer.start(30000);session.start();loop.exec();timer.stop();session.close()
    if result.get('error'):raise RuntimeError(result['step']+': '+result['error'])
    print(json.dumps({'sdk_version':version('mcp'),'protocol':result['protocol'],'checks':['discovery','tool call and output schema','resource list/read','template list/read','prompt list/get']}))


if __name__=='__main__':
    if sys.argv[1:]==['--server']:serve()
    else:run()

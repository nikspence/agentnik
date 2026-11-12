"""Explicitly reviewed MCP tool access for one chat turn."""
import copy
import json
import threading
from PySide6.QtCore import QObject,Signal,QTimer
from .mcp_code import CodingMCPBridge
from .mcp_content import model_tool_result
from .mcp_schema import validate_tool_arguments,validate_tool_result
from .tools import ToolDefinition,ResearchError


class ChatMCP(QObject):
    approval_requested=Signal(object)
    close_requested=Signal()

    def __init__(self,server,config,parent=None,extra_secrets=()):
        super().__init__(parent);self.server=copy.deepcopy(server);self.closing=False
        self.bridge=CodingMCPBridge(server,config,self);self.tools=None
        self.close_requested.connect(self._close_on_gui)
        self.secret_values=[*self.bridge.environment_values.values(),*(secret for secret in extra_secrets if secret)]
        self.definitions=(
            ToolDefinition('mcp_discover','server','Connect to the user-selected MCP server and list its tools. Pass "connect" or the selected server name.',200),
            ToolDefinition('mcp_call','request','Call a discovered MCP tool. request is a JSON object encoded as a string: {"tool":"name","arguments":{...}}.',16000),
        )

    def approve(self,proposal,runtime):
        from .research import scrub
        request={'proposal':scrub(proposal,self.secret_values),'done':threading.Event(),'cancelled':threading.Event(),'approved':False}
        self.approval_requested.emit(request)
        try:
            while not request['done'].wait(.05):runtime.check()
            runtime.check();return request['approved'] is True
        except BaseException:
            request['cancelled'].set();raise

    def validate_call(self,name,args):
        if name=='mcp_discover':
            if args['server'].casefold() not in ('connect',self.server['name'].casefold()):raise ResearchError('Use connect or the selected MCP server name.')
            if self.tools is not None:raise ResearchError('The selected MCP server is already connected.')
            return None
        if name!='mcp_call' or self.tools is None:raise ResearchError('Connect to the selected MCP server before calling a tool.')
        try:
            value=json.loads(args['request'],parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if not isinstance(value,dict) or set(value)!={'tool','arguments'} or not isinstance(value['tool'],str) or not isinstance(value['arguments'],dict):raise ValueError()
            tool=next(item for item in self.tools if item['name']==value['tool'])
            if tool.get('schema_status')!='available' or tool.get('description_clipped') or tool.get('output_schema_status','available')!='available' or tool.get('task_support')=='required':raise ValueError()
            from .mcp_remote import contains_secret
            if any(secret and contains_secret(value,secret) for secret in self.secret_values):raise ValueError()
            validate_tool_arguments(tool['schema'],value['arguments'])
        except (ValueError,StopIteration,RecursionError,UnicodeError):raise ResearchError('MCP tool or arguments are invalid or unsupported.') from None
        return value,tool

    def validate_batch(self,calls):
        if sum(name=='mcp_discover' for name,_ in calls)>1:raise ResearchError('Only one MCP discovery is allowed per batch.')
        for name,args in calls:self.validate_call(name,args)

    def needs_reconnect(self,calls):
        if self.tools is not None or not any(name=='mcp_call' for name,_ in calls):return False
        if any(name!='mcp_call' for name,_ in calls):raise ResearchError('Connect to the selected MCP server before calling a tool.')
        # Check the complete batch's basic structure and credentials before connecting.
        from .mcp_remote import contains_secret
        for _,args in calls:
            try:
                value=json.loads(args['request'],parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                if not isinstance(value,dict) or set(value)!={'tool','arguments'} or not isinstance(value['tool'],str) or not isinstance(value['arguments'],dict):raise ValueError()
                if any(secret and contains_secret(value,secret) for secret in self.secret_values):raise ValueError()
            except (ValueError,RecursionError,UnicodeError):raise ResearchError('MCP tool or arguments are invalid or unsupported.') from None
        return True

    def invoke(self,name,args,runtime):
        server=self.server
        validated=self.validate_call(name,args)
        if name=='mcp_discover':
            runtime.notify('mcp','Connecting to the selected MCP server.')
            response=self.bridge.request('discover',{},runtime)
            if 'error' in response:raise ResearchError(response['error'])
            self.tools=response.get('tool_details',[])
            return {'server':server['name'],'tools':self.tools,'more_tools':response.get('more_tools',False),'notice':'Untrusted server metadata.'}
        value,tool=validated
        response=self.bridge.request('call',{'tool':tool,'arguments':value['arguments']},runtime)
        if 'error' in response:raise ResearchError(response['error']+(' The call may have completed; inspect server state before retrying.' if response.get('call_uncertain') else ''))
        try:
            validate_tool_result(tool,response.get('call_result'))
            result,user_text,user_nontext=model_tool_result(response['call_result'])
        except ValueError:raise ResearchError('MCP output validation failed. The call may have completed; inspect server state before retrying.') from None
        if user_text:
            text='\n'.join(user_text);runtime.notify('mcp_user',text[:400]+(' [truncated]' if len(text)>400 else ''))
        if user_nontext:runtime.notify('mcp_user',str(user_nontext)+' user-directed non-text block(s) not displayed.')
        return {'result':result,'notice':'Untrusted MCP tool output.'}

    def _close_on_gui(self):
        if self.closing:return
        self.closing=True;self.bridge.close()
        # Remote shutdown has its own three-second deadline; keep its owner alive
        # until that cleanup can finish, then release the per-turn controller.
        QTimer.singleShot(3500,self.deleteLater)

    def close(self):self.close_requested.emit()

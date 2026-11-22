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
        except (ValueError,RecursionError,UnicodeError):raise ResearchError('MCP request must be a JSON string containing exactly tool and arguments.') from None
        tool=next((item for item in self.tools if item['name']==value['tool']),None)
        if not tool:raise ResearchError('MCP tool was not found in the selected server tool list.')
        if tool.get('schema_status')!='available' or tool.get('description_clipped') or tool.get('output_schema_status','available')!='available' or tool.get('task_support')=='required':raise ResearchError('MCP tool metadata is incomplete or its execution mode is unsupported.')
        from .mcp_remote import contains_secret
        if any(secret and contains_secret(value,secret) for secret in self.secret_values):raise ResearchError('MCP tool arguments are invalid or unsupported.')
        try:validate_tool_arguments(tool['schema'],value['arguments'])
        except (ValueError,RecursionError,UnicodeError):raise ResearchError('MCP tool arguments do not match its supported input schema.') from None
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
        notify=getattr(runtime,'notify',lambda *_:None)
        validated=self.validate_call(name,args)
        if name=='mcp_discover':
            notify('mcp','Connecting to the selected MCP server.')
            response=self.bridge.request('discover',{},runtime)
            if 'error' in response:raise ResearchError(response['error'])
            self.tools=response.get('tool_details',[])
            notify('mcp','Connected to '+server['name']+'; discovered '+str(len(self.tools))+' tool(s).'+(' More tools were not listed.' if response.get('more_tools',False) else ''))
            return {'server':server['name'],'tools':self.tools,'more_tools':response.get('more_tools',False),'notice':'Untrusted server metadata.'}
        value,tool=validated
        notify('mcp','Calling '+tool['name']+' on '+server['name']+'.')
        response=self.bridge.request('call',{'tool':tool,'arguments':value['arguments']},runtime)
        if 'error' in response:
            notify('mcp','Tool '+tool['name']+' failed.'+(' The call may have completed; inspect server state before retrying.' if response.get('call_uncertain') else ''))
            raise ResearchError(response['error']+(' The call may have completed; inspect server state before retrying.' if response.get('call_uncertain') else ''))
        try:validate_tool_result(tool,response.get('call_result'))
        except ValueError as exc:
            reason=str(exc);notify('mcp','Tool '+tool['name']+': '+reason+' The call may have completed; inspect server state before retrying.')
            raise ResearchError(reason+' The call may have completed; inspect server state before retrying.') from None
        try:result,user_text,user_nontext=model_tool_result(response['call_result'])
        except ValueError:
            notify('mcp','Tool '+tool['name']+' returned invalid content or audience annotations. The call may have completed; inspect server state before retrying.')
            raise ResearchError('MCP result content or audience annotations are invalid. The call may have completed; inspect server state before retrying.') from None
        notify('mcp','Tool '+tool['name']+(' reported an error.' if result.get('isError') is True else ' completed.'))
        if user_text:
            text='\n'.join(user_text);notify('mcp_user',text[:400]+(' [truncated]' if len(text)>400 else ''))
        if user_nontext:notify('mcp_user',str(user_nontext)+' user-directed non-text block(s) not displayed.')
        return {'result':result,'notice':'Untrusted MCP tool output.'}

    def _close_on_gui(self):
        if self.closing:return
        self.closing=True;self.bridge.close()
        # Remote shutdown has its own three-second deadline; keep its owner alive
        # until that cleanup can finish, then release the per-turn controller.
        QTimer.singleShot(3500,self.deleteLater)

    def close(self):self.close_requested.emit()


class MultiChatMCP(QObject):
    """A per-turn ordered collection of independent Chat MCP sessions."""
    approval_requested=Signal(object)
    close_requested=Signal()

    def __init__(self,servers,config,parent=None,extra_secrets=()):
        super().__init__(parent)
        if not isinstance(servers,list) or not 2<=len(servers)<=5:raise ValueError('Select two to five MCP servers.')
        if len({server['name'].casefold() for server in servers})!=len(servers):raise ValueError('MCP servers must be distinct.')
        self.controllers=[ChatMCP(server,config,self,extra_secrets) for server in servers]
        self.discovery_call_count=len(self.controllers)
        self.secret_values=[secret for controller in self.controllers for secret in controller.secret_values]
        self.tools=None;self.more_tools=False;self.failed=False;self.closing=False
        self.close_requested.connect(self._close_on_gui)
        self.definitions=(
            ToolDefinition('mcp_discover','server','Connect to all selected MCP servers in precedence order. Pass "connect".',200),
            ToolDefinition('mcp_call','request','Call an MCP tool. request is a JSON string: {"tool":"name","arguments":{...},"server":"optional server name"}. The first server wins conflicting names.',16000),
        )

    def _parse(self,args):
        from .mcp_remote import contains_secret
        try:
            value=json.loads(args['request'],parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if not isinstance(value,dict) or set(value) not in ({'tool','arguments'},{'server','tool','arguments'}) or not isinstance(value['tool'],str) or not isinstance(value['arguments'],dict) or ('server' in value and not isinstance(value['server'],str)):raise ValueError()
            if any(secret and contains_secret(value,secret) for secret in self.secret_values):raise ValueError()
            return value
        except (KeyError,TypeError,ValueError,RecursionError,UnicodeError):raise ResearchError('MCP request must contain a tool, arguments object, and optional selected server.') from None

    def validate_call(self,name,args):
        if self.failed:raise ResearchError('An MCP server connection failed; start a new run after inspecting its state.')
        if name=='mcp_discover':
            if args.get('server','').casefold()!='connect' or self.tools is not None:raise ResearchError('Use connect once to discover the selected MCP servers.')
            return None
        if name!='mcp_call' or self.tools is None:raise ResearchError('Connect to the selected MCP servers before calling a tool.')
        value=self._parse(args)
        if self.more_tools:raise ResearchError('An MCP tool list is incomplete; precedence cannot be determined safely.')
        controller=next((item for item in self.controllers if any(tool['name']==value['tool'] for tool in item.tools)),None)
        if controller is None:raise ResearchError('MCP tool was not found on the selected servers.')
        if 'server' in value and value['server'].casefold()!=controller.server['name'].casefold():raise ResearchError('The tool belongs to the higher-priority MCP server '+controller.server['name']+'.')
        payload={'request':json.dumps({'tool':value['tool'],'arguments':value['arguments']},ensure_ascii=False)}
        controller.validate_call('mcp_call',payload)
        return controller,payload

    def validate_batch(self,calls):
        if sum(name=='mcp_discover' for name,_ in calls)>1 or (len(calls)>1 and any(name=='mcp_discover' for name,_ in calls)):raise ResearchError('Discover the selected MCP servers separately before tool calls.')
        for name,args in calls:self.validate_call(name,args)

    def needs_reconnect(self,calls):
        if self.tools is not None or not any(name=='mcp_call' for name,_ in calls):return False
        if any(name!='mcp_call' for name,_ in calls):raise ResearchError('Connect to the selected MCP servers before calling a tool.')
        for _,args in calls:self._parse(args)
        return True

    def invoke(self,name,args,runtime):
        validated=self.validate_call(name,args)
        if name=='mcp_call':
            controller,payload=validated
            return controller.invoke(name,payload,runtime)
        # The caller charges one discovery; additional server requests are charged here.
        discovered=[];seen=set();self.more_tools=False
        if runtime.calls+len(self.controllers)-1>runtime.limits.calls:raise ResearchError('Not enough tool calls remain to discover all selected MCP servers.')
        try:
            for index,controller in enumerate(self.controllers):
                if index:runtime.charge('calls',1,runtime.limits.calls)
                response=controller.invoke('mcp_discover',{'server':'connect'},runtime)
                self.more_tools=self.more_tools or bool(response.get('more_tools'))
                for tool in response['tools']:
                    if tool['name'] not in seen:
                        seen.add(tool['name']);discovered.append(dict(tool,server=controller.server['name']))
        except BaseException:
            self.failed=True
            for controller in self.controllers:controller.close()
            raise
        self.tools=discovered
        return {'servers':[item.server['name'] for item in self.controllers],'tools':discovered,'more_tools':self.more_tools,'notice':'Untrusted MCP server metadata; first server wins conflicting tool names.'}

    def _close_on_gui(self):
        if self.closing:return
        self.closing=True
        for controller in self.controllers:controller.close()
        QTimer.singleShot(3500,self.deleteLater)

    def close(self):self.close_requested.emit()

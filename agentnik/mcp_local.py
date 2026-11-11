"""Persistent, explicitly started MCP stdio session."""
import json
import os
import shutil
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from .mcp_support import MAX_OUTPUT, initialize_request, parse_initialize, resolve_environment_references
from .mcp_remote import MAX_PAGES, MAX_TOOLS, MAX_DETAILS, preview_tool, contains_secret
from .mcp_resources import ResourcePages,TemplatePages,expand_template,parse_resource_text
from .mcp_prompts import PromptPages,parse_prompt_messages,validate_prompt_arguments


class LocalSession(QObject):
    discovered = Signal(object)
    called = Signal(object)
    ended = Signal(object)
    resources = Signal(object)
    prompts = Signal(object)

    def __init__(self, command, args, parent=None, env_refs=None, env_values=None):
        super().__init__(parent)
        self.process = QProcess(self)
        values=resolve_environment_references(env_refs or {}) if env_values is None else dict(env_values)
        self.environment_secrets=[value for value in values.values() if value]
        if values:
            environment=QProcessEnvironment.systemEnvironment()
            for name,value in values.items():environment.insert(name,value)
            self.process.setProcessEnvironment(environment)
        # Windows cannot execute npm's .cmd shim directly through CreateProcess.
        if os.name == 'nt' and command.lower() in ('npx', 'npx.cmd'):
            shim = shutil.which('npx.cmd')
            node = shutil.which('node.exe')
            cli = Path(shim).parent / 'node_modules' / 'npm' / 'bin' / 'npx-cli.js' if shim else None
            if node and cli and cli.is_file():
                command, args = node, [str(cli), *args]
        self.process.setProgram(command)
        self.process.setArguments(args)
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.started.connect(lambda: self.send(initialize_request()))
        self.process.errorOccurred.connect(lambda _: self.fail('Unable to start or communicate with local MCP server.'))
        self.process.finished.connect(lambda *_: self.fail('Local MCP server exited.'))
        self.timer = QTimer(self); self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.fail('Local MCP request timed out.'))
        self.buffer = bytearray(); self.phase = 'initialize'; self.next_id = 1
        self.pages = 0; self.names = []; self.details = []; self.detail_bytes = 0; self.cursors = set()
        self.info = None; self.closed = False; self.invocation = None

    def start(self):
        self.timer.start(30000); self.process.start()

    def send(self, message):
        payload = (json.dumps(message, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
        if self.process.write(payload) != len(payload): self.fail('Unable to send MCP request.')

    def read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer) > MAX_OUTPUT:
            self.fail('MCP response exceeded the output limit.'); return
        while b'\n' in self.buffer and not self.closed:
            line, _, rest = self.buffer.partition(b'\n'); self.buffer = bytearray(rest)
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or message.get('jsonrpc') != '2.0': raise ValueError()
                if any(contains_secret(message,secret) for secret in self.environment_secrets):
                    self.fail('MCP response contained a mapped environment value and was blocked.');return
                if 'id' not in message:
                    if message.get('method') in ('notifications/tools/list_changed','notifications/resources/list_changed','notifications/prompts/list_changed'):
                        self.fail('MCP tools changed; reconnect before making another call.')
                    continue
                if type(message['id']) is not int or message['id'] != self.next_id: raise ValueError()
                if 'error' in message:
                    if self.phase in ('prompt_list','prompt_get'):
                        self.phase='ready';self.timer.stop();self.prompts.emit({'error':'MCP server returned a prompt error.'});continue
                    if self.phase in ('resource_list','resource_read','template_list'):
                        self.phase='ready';self.timer.stop();self.resources.emit({'error':'MCP server returned a resource error.'});continue
                    if self.phase == 'call':
                        self.phase = 'ready'; self.timer.stop(); self.called.emit({'error': 'MCP server returned a tool error.'}); continue
                    raise ValueError()
                if self.phase == 'initialize':
                    self.info = parse_initialize(line, ('2025-11-25','2025-06-18','2025-03-26','2024-11-05'));  self.send({'jsonrpc':'2.0','method':'notifications/initialized'})
                    if 'tools' not in self.info['capabilities']:
                        self.finish_discovery(False); continue
                    self.list_page(None); continue
                result = message.get('result')
                if not isinstance(result, dict): raise ValueError()
                if self.phase == 'prompt_list':
                    cursor,outcome=self.prompt_pages.accept(result)
                    if cursor:self.prompt_list_page(cursor);continue
                    self.prompt_items=outcome['prompts']
                    if self.prompt_invocation:
                        expected=self.prompt_invocation['prompt'];current=next((x for x in self.prompt_items if x['name']==expected['name']),None)
                        if current!=expected:self.fail('MCP prompt definition changed.');return
                        args=self.prompt_invocation['arguments'];self.prompt_invocation=None;self.phase='prompt_get';self.next_id+=1
                        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'prompts/get','params':{'name':current['name'],'arguments':args}});continue
                    self.phase='ready';self.timer.stop();self.prompts.emit(outcome);continue
                if self.phase == 'prompt_get':
                    outcome=parse_prompt_messages(result);self.phase='ready';self.timer.stop();self.prompts.emit(outcome);continue
                if self.phase == 'template_list':
                    cursor,outcome=self.template_pages.accept(result)
                    if cursor:self.template_list_page(cursor);continue
                    self.template_items=outcome['templates'];self.phase='ready';self.timer.stop();self.resources.emit(outcome);continue
                if self.phase == 'resource_list':
                    cursor,outcome=self.resource_pages.accept(result)
                    if cursor:self.resource_list_page(cursor);continue
                    self.resource_items=outcome['resources'];self.phase='ready';self.timer.stop();self.resources.emit(outcome);continue
                if self.phase == 'resource_read':
                    outcome=parse_resource_text(result,self.resource_uri);self.phase='ready';self.timer.stop();self.resources.emit(outcome);continue
                if self.phase == 'call':
                    if not isinstance(result.get('content'), list) or ('isError' in result and type(result['isError']) is not bool): raise ValueError()
                    self.phase = 'ready'; self.timer.stop(); self.called.emit({'call_result':result}); continue
                if self.phase != 'tools' or not isinstance(result.get('tools'), list) or len(result['tools']) > MAX_TOOLS: raise ValueError()
                for item in result['tools']:
                    name = item.get('name') if isinstance(item, dict) else None
                    if not isinstance(name, str) or not name or len(name)>128 or any(ord(ch)<32 or ord(ch)==127 for ch in name) or name in self.names: raise ValueError()
                    self.names.append(name)
                    if len(self.details) < MAX_TOOLS:
                        detail = preview_tool(item); detail['name'] = name
                        size = len(json.dumps(detail, ensure_ascii=True).encode('ascii'))
                        if self.detail_bytes + size > MAX_DETAILS:
                            detail = {'name':name,'description':'','description_clipped':True,'schema':None,'schema_status':'details budget exceeded'}
                        self.detail_bytes += size; self.details.append(detail)
                cursor = result.get('nextCursor')
                if cursor is not None:
                    if not isinstance(cursor,str) or not cursor or len(cursor)>1024 or cursor in self.cursors: raise ValueError()
                    self.cursors.add(cursor)
                if cursor and self.pages < MAX_PAGES and len(self.names) < MAX_TOOLS: self.list_page(cursor)
                else: self.finish_discovery(bool(cursor) or len(self.names)>MAX_TOOLS)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.fail('Invalid or unsupported local MCP server response.'); return

    def list_page(self, cursor):
        self.phase = 'tools'; self.pages += 1; self.next_id += 1
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'tools/list','params':{'cursor':cursor} if cursor else {}})

    def finish_discovery(self, more):
        if self.invocation:
            expected=self.invocation['tool']
            current=next((item for item in self.details if item['name']==expected['name']),None)
            if current!=expected or current.get('schema_status')!='available' or current.get('task_support')=='required':
                self.fail('MCP tool definition changed or requires unsupported task execution.');return
            args=self.invocation['arguments'];self.invocation=None
            self.phase='call';self.next_id+=1
            self.send({'jsonrpc':'2.0','id':self.next_id,'method':'tools/call','params':{'name':current['name'],'arguments':args}});return
        self.phase = 'ready'; self.timer.stop()
        self.info.update(tools=self.names[:MAX_TOOLS], tool_details=self.details, more_tools=more)
        self.discovered.emit(self.info)

    def call(self, tool, args):
        if self.closed or self.phase != 'ready' or tool not in self.details or tool.get('task_support')=='required': return False
        self.invocation={'tool':tool,'arguments':args}
        self.pages=0;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set()
        self.timer.start(30000);self.list_page(None)
        return True

    def list_resources(self):
        if self.closed or self.phase!='ready' or 'resources' not in self.info['capabilities']:return False
        self.resource_items=[];self.resource_pages=ResourcePages();self.phase='resource_list';self.timer.start(30000)
        self.resource_list_page(None);return True

    def resource_list_page(self,cursor):
        self.next_id+=1
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'resources/list','params':{'cursor':cursor} if cursor else {}})

    def read_resource(self,uri):
        if self.closed or self.phase!='ready' or uri not in [item['uri'] for item in getattr(self,'resource_items',[])]:return False
        self.resource_uri=uri;self.phase='resource_read';self.next_id+=1;self.timer.start(30000)
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'resources/read','params':{'uri':uri}});return True

    def list_resource_templates(self):
        if self.closed or self.phase!='ready' or 'resources' not in self.info['capabilities']:return False
        self.template_items=[];self.template_pages=TemplatePages();self.phase='template_list';self.timer.start(30000)
        self.template_list_page(None);return True

    def template_list_page(self,cursor):
        self.next_id+=1
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'resources/templates/list','params':{'cursor':cursor} if cursor else {}})

    def read_resource_template(self,template,arguments,uri):
        if self.closed or self.phase!='ready' or template not in getattr(self,'template_items',[]) or not template['supported']:return False
        try:
            if expand_template(template['uriTemplate'],arguments)!=uri:return False
        except (ValueError,UnicodeError):return False
        self.resource_uri=uri;self.phase='resource_read';self.next_id+=1;self.timer.start(30000)
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'resources/read','params':{'uri':uri}});return True

    def list_prompts(self,invocation=None):
        if self.closed or self.phase!='ready' or 'prompts' not in self.info['capabilities']:return False
        if invocation:
            if invocation['prompt'] not in getattr(self,'prompt_items',[]):return False
            try:validate_prompt_arguments(invocation['prompt'],invocation['arguments'])
            except (ValueError,UnicodeError,RecursionError):return False
        self.prompt_invocation=invocation;self.prompt_items=[];self.prompt_pages=PromptPages();self.phase='prompt_list';self.timer.start(30000)
        self.prompt_list_page(None);return True

    def prompt_list_page(self,cursor):
        self.next_id+=1
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'prompts/list','params':{'cursor':cursor} if cursor else {}})

    def fail(self, message):
        from shiboken6 import isValid
        if not isValid(self) or self.closed: return
        uncertain = self.phase == 'call'; self.close()
        self.ended.emit({'error':message,'call_uncertain':uncertain})

    def close(self):
        if self.closed: return
        self.closed = True
        from shiboken6 import isValid
        self.environment_secrets=[]
        if not isValid(self.process):return
        if isValid(self.timer):self.timer.stop()
        self.process.errorOccurred.disconnect(); self.process.finished.disconnect()
        self.process.closeWriteChannel()
        if not self.process.waitForFinished(500):
            self.process.kill(); self.process.waitForFinished(500)

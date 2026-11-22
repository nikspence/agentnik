"""Persistent, explicitly started MCP stdio session."""
import json
import os
import shutil
import time
import uuid
from collections import deque
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from .mcp_support import response_limit, initialize_request, parse_initialize, resolve_environment_references, rpc_error, server_timeout,progress_notice,created_task_id,validate_task_result,invalidate_server_list,MCPListChangedError,task_status_notice,server_log_notice
from .mcp_remote import MAX_PAGES, MAX_TOOLS, MAX_DETAILS, preview_tool, contains_secret
from .mcp_resources import ResourcePages,TemplatePages,expand_template,parse_resource_contents,tool_resource_links,merge_resource_links
from .mcp_prompts import PromptPages,parse_prompt_messages,validate_prompt_arguments
from .mcp_2026 import prepare_request,parse_discovery,INPUT_REQUIRED_ERROR


class LocalSession(QObject):
    discovered = Signal(object)
    called = Signal(object)
    ended = Signal(object)
    resources = Signal(object)
    prompts = Signal(object)
    progress = Signal(object)
    shutdown_finished = Signal(object)

    def __init__(self, command, args, parent=None, env_refs=None, env_values=None, timeout_seconds=60, working_directory=''):
        super().__init__(parent)
        if not isinstance(working_directory,str) or (working_directory and not os.path.isabs(working_directory)):raise ValueError('The MCP working directory must be absolute on this system.')
        self.timeout_ms=1000*server_timeout({'timeout_seconds':timeout_seconds})
        self.process = QProcess(self);self.job=None
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
        if working_directory:self.process.setWorkingDirectory(working_directory)
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.started.connect(self.started)
        self.process.errorOccurred.connect(lambda _: self.fail('Unable to start or communicate with local MCP server.'))
        self.process.finished.connect(lambda *_: self.fail('Local MCP server exited.'))
        self.timer = QTimer(self); self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.fail('Local MCP request timed out.'))
        self.probe_timer=QTimer(self);self.probe_timer.setSingleShot(True);self.probe_timer.timeout.connect(self.probe_modern)
        self.subscription_timer=QTimer(self);self.subscription_timer.setSingleShot(True);self.subscription_timer.timeout.connect(lambda:self.stop_subscription('MCP change notification subscription was not acknowledged; list resources and prompts again.'))
        self.subscription_retry=QTimer(self);self.subscription_retry.setSingleShot(True);self.subscription_retry.timeout.connect(self.retry_subscription)
        self.buffer = bytearray(); self.phase = 'initialize'; self.next_id = 1
        self.pages = 0; self.names = []; self.details = []; self.detail_bytes = 0; self.cursors = set()
        self.info = None; self.closed = False; self.invocation = None; self.server_requests=deque();self.resource_links=[];self.progress_token=None;self.progress_last=None;self.progress_count=0;self.progress_emitted_at=0;self.task_mode=False;self.task_id=None;self.task_cancelled=None;self.cancelled_result_id=None;self.task_status_last=None;self.task_status_count=0;self.log_count=0;self.request_active=False;self.modern=False;self.probe_id=None;self.ignored_id=None;self.subscription_id=-1;self.subscription_active=False;self.subscription_ack=None;self.retired_subscriptions=deque(maxlen=32)

    def start(self):
        if os.name=='nt':
            try:
                from .shell import WindowsJob
                self.job=WindowsJob()
            except OSError:
                self.fail('Unable to prepare local MCP process cleanup.');return
        self.timer.start(self.timeout_ms); self.process.start()

    def started(self):
        if self.job:
            try:self.job.assign_pid(self.process.processId())
            except OSError:self.fail('Unable to isolate the local MCP process for cleanup.');return
        self.send(initialize_request())
        if not self.closed:self.probe_timer.start(min(1000,max(250,self.timeout_ms//3)))

    def probe_modern(self):
        if self.closed or self.phase!='initialize' or self.probe_id is not None:return
        self.probe_id=2
        message,_=prepare_request({'jsonrpc':'2.0','id':self.probe_id,'method':'server/discover','params':{}})
        self.send(message)

    def send(self, message):
        if self.modern and 'id' in message and 'method' in message:message,_=prepare_request(message)
        payload = (json.dumps(message, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
        if 'id' in message:self.request_active=True
        if self.process.write(payload) != len(payload): self.fail('Unable to send MCP request.')

    def open_subscription(self):
        filters=self.info.get('subscription_filters',{})
        if not filters:return
        self.subscription_active=True;self.subscription_ack=None
        self.send({'jsonrpc':'2.0','id':self.subscription_id,'method':'subscriptions/listen','params':{'notifications':filters}})
        if not self.closed:self.subscription_timer.start(self.timeout_ms)

    def stop_subscription(self,message,cancel=True):
        if not self.subscription_active:return
        self.subscription_active=False;self.subscription_ack=None;self.subscription_timer.stop();self.retired_subscriptions.append(self.subscription_id)
        if cancel and self.process.state()==QProcess.ProcessState.Running:
            payload=(json.dumps({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':self.subscription_id}})+'\n').encode('ascii');self.process.write(payload)
        self.resource_items=[];self.template_items=[];self.prompt_items=[];self.progress.emit(message)

    def retry_subscription(self):
        if self.closed or self.subscription_active or not self.modern:return
        self.subscription_id-=1;self.open_subscription()

    def subscription_notification(self,message):
        method=message.get('method');params=message.get('params')
        if method=='notifications/cancelled' and isinstance(params,dict) and params.get('requestId') in self.retired_subscriptions:return
        if method=='notifications/cancelled' and isinstance(params,dict) and params.get('requestId')==self.subscription_id:
            self.stop_subscription('MCP change notification subscription ended; list resources and prompts again.',cancel=False)
            if not self.closed:self.subscription_retry.start(1000)
            return
        if not self.subscription_active:return
        meta=params.get('_meta') if isinstance(params,dict) else None
        if isinstance(meta,dict) and meta.get('io.modelcontextprotocol/subscriptionId') in self.retired_subscriptions:return
        if not isinstance(meta,dict) or type(meta.get('io.modelcontextprotocol/subscriptionId')) is not int or meta['io.modelcontextprotocol/subscriptionId']!=self.subscription_id:
            self.stop_subscription('MCP change notification subscription returned an invalid message; list resources and prompts again.');return
        if self.subscription_ack is None:
            selected=params.get('notifications');requested=self.info['subscription_filters']
            if method!='notifications/subscriptions/acknowledged' or not isinstance(selected,dict) or any(key not in requested or type(value) is not bool or value and not requested[key] for key,value in selected.items()):
                self.stop_subscription('MCP change notification subscription returned an invalid message; list resources and prompts again.');return
            self.subscription_ack={key for key,value in selected.items() if value};self.subscription_timer.stop();missing=set(requested)-self.subscription_ack
            if missing:
                if 'resourcesListChanged' in missing:self.resource_items=[];self.template_items=[]
                if 'promptsListChanged' in missing:self.prompt_items=[]
                self.progress.emit('MCP server declined some change notifications; relist resources and prompts before using them.')
            return
        mapping={'notifications/tools/list_changed':'toolsListChanged','notifications/resources/list_changed':'resourcesListChanged','notifications/prompts/list_changed':'promptsListChanged'}
        if method not in mapping or mapping[method] not in self.subscription_ack:
            self.stop_subscription('MCP change notification subscription returned an invalid message; list resources and prompts again.');return
        notice=invalidate_server_list(self,method)
        if notice:self.progress.emit(notice)

    def read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b'\n' in self.buffer and not self.closed:
            line, _, rest = self.buffer.partition(b'\n'); self.buffer = bytearray(rest)
            if len(line)>response_limit(self.phase):
                self.fail('MCP response exceeded the output limit.'); return
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or message.get('jsonrpc') != '2.0': raise ValueError()
                if any(contains_secret(message,secret) for secret in self.environment_secrets):
                    self.fail('MCP response contained a mapped environment value and was blocked.');return
                if 'method' in message and 'id' in message:
                    if self.modern:raise ValueError('Unexpected server request in MCP 2026')
                    ident=message['id'];method=message['method'];params=message.get('params')
                    if (type(ident) is not int and (not isinstance(ident,str) or len(ident)>128)) or not isinstance(method,str) or not method or len(method)>256 or (params is not None and not isinstance(params,dict)) or 'result' in message or 'error' in message:raise ValueError()
                    now=time.monotonic()
                    while self.server_requests and self.server_requests[0]<=now-10:self.server_requests.popleft()
                    if len(self.server_requests)>=32:raise ValueError('Too many MCP server requests')
                    self.server_requests.append(now)
                    response={'jsonrpc':'2.0','id':ident}
                    if method=='ping':response['result']={}
                    else:response['error']={'code':-32601,'message':'Method not supported'}
                    self.send(response);continue
                if 'id' not in message:
                    if self.modern and message.get('method') in ('notifications/subscriptions/acknowledged','notifications/cancelled','notifications/tools/list_changed','notifications/resources/list_changed','notifications/prompts/list_changed'):
                        self.subscription_notification(message);continue
                    if self.phase in ('call','task_result') and self.log_count<20:
                        detail=server_log_notice(message)
                        if detail:self.log_count+=1;self.progress.emit(detail)
                    if self.phase=='task_result' and self.task_status_count<40:
                        status=task_status_notice(message,self.task_id,self.task_status_last)
                        if status:self.task_status_last,detail=status;self.task_status_count+=1;self.progress.emit(detail)
                    if self.phase in ('call','task_result') and self.progress_token is not None:
                        notice=progress_notice(message,self.progress_token,self.progress_last)
                        if notice:
                            self.progress_last,detail=notice;now=time.monotonic()
                            if self.progress_count<40 and now-self.progress_emitted_at>=.25:
                                self.progress_count+=1;self.progress_emitted_at=now;self.progress.emit(detail)
                    if message.get('method') in ('notifications/tools/list_changed','notifications/resources/list_changed','notifications/prompts/list_changed'):
                        notice=invalidate_server_list(self,message['method'])
                        if notice:self.progress.emit(notice)
                    continue
                if self.phase=='task_cancel' and type(message['id']) is int and message['id']==self.cancelled_result_id:continue
                if self.modern and type(message['id']) is int and message['id']==self.subscription_id:
                    if self.subscription_active:
                        self.stop_subscription('MCP change notification subscription ended; list resources and prompts again.',cancel=False)
                        if not self.closed:self.subscription_retry.start(1000)
                    continue
                if self.modern and type(message['id']) is int and message['id'] in self.retired_subscriptions:continue
                if type(message['id']) is int and message['id']==self.ignored_id:
                    self.ignored_id=None;continue
                if self.phase=='initialize' and type(message['id']) is int and message['id']==self.probe_id:
                    if 'error' in message:
                        error=message.get('error')
                        if isinstance(error,dict) and error.get('code')==-32022:self.fail('MCP server does not support the requested protocol version.');return
                        self.probe_id=None;continue
                    try:parse_discovery(message.get('result'))
                    except (ValueError,TypeError,RecursionError):self.probe_id=None;continue
                    self.modern=True;self.phase='modern_discovery';self.ignored_id=1;self.next_id=self.probe_id;self.probe_id=None
                if type(message['id']) is not int or message['id'] != self.next_id: raise ValueError()
                self.request_active=False
                if self.phase=='task_cancel':
                    task=message.get('result')
                    self.task_cancelled=isinstance(task,dict) and task.get('taskId')==self.task_id and task.get('status')=='cancelled' and 'error' not in message
                    self._close_now();return
                if 'error' in message:
                    if self.phase=='initialize' and isinstance(message['error'],dict) and message['error'].get('code') in (-32601,-32022):
                        self.probe_timer.stop()
                        if self.probe_id is not None:
                            self.modern=True;self.phase='modern_discovery';self.next_id=self.probe_id;self.probe_id=None;continue
                        self.modern=True;self.phase='modern_discovery';self.next_id+=1
                        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'server/discover','params':{}});continue
                    error=rpc_error(message)
                    if self.phase=='completion':
                        self.phase='ready';self.timer.stop();self.called.emit({'error':error});continue
                    if self.phase in ('prompt_list','prompt_get'):
                        self.phase='ready';self.timer.stop();self.prompts.emit({'error':error});continue
                    if self.phase in ('resource_list','resource_read','template_list'):
                        self.phase='ready';self.timer.stop();self.resources.emit({'error':error});continue
                    self.fail(error);return
                if self.phase == 'initialize':
                    self.probe_timer.stop()
                    if self.probe_id is not None:self.ignored_id=self.probe_id;self.next_id=self.probe_id;self.probe_id=None
                    self.info = parse_initialize(line, ('2025-11-25','2025-06-18','2025-03-26','2024-11-05'));  self.send({'jsonrpc':'2.0','method':'notifications/initialized'})
                    if 'tools' not in self.info['capabilities']:
                        self.finish_discovery(False); continue
                    self.list_page(None); continue
                result = message.get('result')
                if not isinstance(result, dict): raise ValueError()
                if self.modern and self.phase in ('call','resource_read','prompt_get') and result.get('resultType')=='input_required':
                    self.fail(INPUT_REQUIRED_ERROR);return
                if self.phase=='modern_discovery':
                    self.info=parse_discovery(result)
                    self.open_subscription()
                    if 'tools' not in self.info['capabilities']:self.finish_discovery(False);continue
                    self.list_page(None);continue
                if self.phase=='completion':
                    from .mcp_completion import parse_completion
                    outcome=parse_completion(result)
                    if any(contains_secret(outcome,secret) for secret in self.environment_secrets):self.fail('MCP response contained a mapped environment value and was blocked.');return
                    self.phase='ready';self.timer.stop();self.called.emit({'completion':outcome});continue
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
                    outcome=parse_prompt_messages(result)
                    if any(contains_secret(outcome,secret) for secret in self.environment_secrets):self.fail('MCP response contained a mapped environment value and was blocked.');return
                    self.phase='ready';self.timer.stop();self.prompts.emit(outcome);continue
                if self.phase == 'template_list':
                    cursor,outcome=self.template_pages.accept(result)
                    if cursor:self.template_list_page(cursor);continue
                    self.template_items=outcome['templates'];self.phase='ready';self.timer.stop();self.resources.emit(outcome);continue
                if self.phase == 'resource_list':
                    cursor,outcome=self.resource_pages.accept(result)
                    if cursor:self.resource_list_page(cursor);continue
                    self.resource_items=outcome['resources'];self.phase='ready';self.timer.stop();self.resources.emit(outcome);continue
                if self.phase == 'resource_read':
                    outcome=parse_resource_contents(result,self.resource_uri)
                    if any(contains_secret(outcome,secret) for secret in self.environment_secrets):self.fail('MCP response contained a mapped environment value and was blocked.');return
                    self.phase='ready';self.timer.stop();self.resources.emit(outcome);continue
                if self.phase=='call' and self.task_mode:
                    self.task_id=created_task_id(result);self.task_status_last='working';self.task_status_count=0;self.phase='task_result';self.next_id+=1
                    self.progress.emit('Task started: '+self.task_id+'; awaiting result.')
                    self.send({'jsonrpc':'2.0','id':self.next_id,'method':'tasks/result','params':{'taskId':self.task_id}});continue
                if self.phase in ('call','task_result'):
                    if self.modern and result.get('resultType','complete')!='complete':raise ValueError('MCP multi-round-trip input is not supported')
                    if self.phase=='task_result':validate_task_result(result,self.task_id)
                    from .mcp_content import decode_tool_text_resources,normalize_tool_result
                    result=normalize_tool_result(result)
                    result=decode_tool_text_resources(result)
                    if any(contains_secret(result,secret) for secret in self.environment_secrets):self.fail('MCP response contained a mapped environment value and was blocked.');return
                    self.resource_links=merge_resource_links(self.resource_links,tool_resource_links(result))
                    self.progress_token=None;self.task_id=None;self.task_mode=False;self.phase = 'ready'; self.timer.stop(); self.called.emit({'call_result':result}); continue
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
            except MCPListChangedError as exc:
                self.fail(str(exc));return
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.fail('Invalid or unsupported local MCP server response.'); return
        if not self.closed and len(self.buffer)>response_limit(self.phase):
            self.fail('MCP response exceeded the output limit.')

    def list_page(self, cursor):
        self.phase = 'tools'; self.pages += 1; self.next_id += 1
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'tools/list','params':{'cursor':cursor} if cursor else {}})

    def finish_discovery(self, more):
        if self.invocation:
            expected=self.invocation['tool']
            current=next((item for item in self.details if item['name']==expected['name']),None)
            if current!=expected or current.get('schema_status')!='available' or not self.supports_tool(current):
                self.fail('MCP tool definition changed or requires unsupported task execution.');return
            if self.invocation.get('verify_only'):
                self.invocation=None;self.phase='ready';self.timer.stop();self.called.emit({'verified':True});return
            args=self.invocation['arguments'];self.invocation=None
            self.phase='call';self.next_id+=1;self.progress_token=uuid.uuid4().hex;self.progress_last=None;self.progress_count=0;self.progress_emitted_at=0;self.log_count=0
            self.task_mode=current.get('task_support')=='required';self.task_id=None
            params={'name':current['name'],'arguments':args,'_meta':{'progressToken':self.progress_token}}
            if self.task_mode:params['task']={}
            self.send({'jsonrpc':'2.0','id':self.next_id,'method':'tools/call','params':params});return
        self.phase = 'ready'; self.timer.stop()
        self.info.update(tools=self.names[:MAX_TOOLS], tool_details=self.details, more_tools=more)
        self.discovered.emit(self.info)

    def supports_tool(self,tool):
        return tool.get('task_support')!='required' or bool((self.info or {}).get('task_capabilities',{}).get('tool_calls'))

    def verify_tool(self, tool):
        if self.closed or self.phase != 'ready' or tool not in self.details or not self.supports_tool(tool): return False
        self.invocation={'tool':tool,'verify_only':True}
        self.pages=0;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set()
        self.timer.start(self.timeout_ms);self.list_page(None)
        return True

    def call(self, tool, args):
        if self.closed or self.phase != 'ready' or tool not in self.details or not self.supports_tool(tool): return False
        self.invocation={'tool':tool,'arguments':args}
        self.pages=0;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set()
        self.timer.start(self.timeout_ms);self.list_page(None)
        return True

    def list_resources(self):
        if self.closed or self.phase!='ready' or 'resources' not in self.info['capabilities']:return False
        self.resource_items=[];self.resource_pages=ResourcePages();self.phase='resource_list';self.timer.start(self.timeout_ms)
        self.resource_list_page(None);return True

    def resource_list_page(self,cursor):
        self.next_id+=1
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'resources/list','params':{'cursor':cursor} if cursor else {}})

    def read_resource(self,uri):
        if self.closed or self.phase!='ready' or uri not in [item['uri'] for item in getattr(self,'resource_items',[])+self.resource_links]:return False
        self.resource_uri=uri;self.phase='resource_read';self.next_id+=1;self.timer.start(self.timeout_ms)
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'resources/read','params':{'uri':uri}});return True

    def list_resource_templates(self):
        if self.closed or self.phase!='ready' or 'resources' not in self.info['capabilities']:return False
        self.template_items=[];self.template_pages=TemplatePages();self.phase='template_list';self.timer.start(self.timeout_ms)
        self.template_list_page(None);return True

    def template_list_page(self,cursor):
        self.next_id+=1
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'resources/templates/list','params':{'cursor':cursor} if cursor else {}})

    def read_resource_template(self,template,arguments,uri):
        if self.closed or self.phase!='ready' or template not in getattr(self,'template_items',[]) or not template['supported']:return False
        try:
            if expand_template(template['uriTemplate'],arguments)!=uri:return False
        except (ValueError,UnicodeError):return False
        self.resource_uri=uri;self.phase='resource_read';self.next_id+=1;self.timer.start(self.timeout_ms)
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'resources/read','params':{'uri':uri}});return True

    def list_prompts(self,invocation=None):
        if self.closed or self.phase!='ready' or 'prompts' not in self.info['capabilities']:return False
        if invocation:
            if invocation['prompt'] not in getattr(self,'prompt_items',[]):return False
            try:validate_prompt_arguments(invocation['prompt'],invocation['arguments'])
            except (ValueError,UnicodeError,RecursionError):return False
        self.prompt_invocation=invocation;self.prompt_items=[];self.prompt_pages=PromptPages();self.phase='prompt_list';self.timer.start(self.timeout_ms)
        self.prompt_list_page(None);return True

    def complete_argument(self,kind,target,argument,value,context):
        if self.closed or self.phase!='ready' or 'completions' not in self.info['capabilities']:return False
        if target not in getattr(self,'prompt_items' if kind=='prompt' else 'template_items',[]):return False
        try:
            from .mcp_completion import completion_params
            params=completion_params(kind,target,argument,value,context)
            if any(contains_secret(params,secret) for secret in self.environment_secrets):return False
        except (ValueError,TypeError,UnicodeError,RecursionError):return False
        self.completion_kind=kind;self.phase='completion';self.next_id+=1;self.timer.start(self.timeout_ms)
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'completion/complete','params':params});return True

    def prompt_list_page(self,cursor):
        self.next_id+=1
        self.send({'jsonrpc':'2.0','id':self.next_id,'method':'prompts/list','params':{'cursor':cursor} if cursor else {}})

    def fail(self, message):
        from shiboken6 import isValid
        if not isValid(self) or self.closed: return
        if self.phase=='task_cancel':self.task_cancelled=False;self._close_now();return
        uncertain = self.phase in ('call','task_result')
        if self.task_id:message+=' Task '+self.task_id+' may still be running; inspect the server before retrying.'
        self.close()
        self.ended.emit({'error':message,'call_uncertain':uncertain})

    def close(self):
        if self.closed: return
        if self.phase=='task_cancel':return
        caps=(self.info or {}).get('task_capabilities',{})
        if self.phase=='task_result' and self.task_id and caps.get('cancel'):
            self.task_cancelled=False;self.cancelled_result_id=self.next_id;self.phase='task_cancel';self.next_id+=1;self.timer.start(3000)
            self.send({'jsonrpc':'2.0','id':self.next_id,'method':'tasks/cancel','params':{'taskId':self.task_id}});return
        if self.phase=='call' and not self.task_mode and self.request_active and self.process.state()==QProcess.ProcessState.Running:
            payload=(json.dumps({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':self.next_id}},ensure_ascii=True)+'\n').encode('ascii')
            self.request_active=False;self.process.write(payload)
        if self.subscription_active and self.process.state()==QProcess.ProcessState.Running:
            payload=(json.dumps({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':self.subscription_id}})+'\n').encode('ascii');self.process.write(payload);self.subscription_active=False
        self._close_now()

    def _close_now(self):
        if self.closed:return
        self.closed = True
        from shiboken6 import isValid
        self.environment_secrets=[]
        if isValid(self.timer):self.timer.stop()
        if isValid(self.probe_timer):self.probe_timer.stop()
        if isValid(self.subscription_timer):self.subscription_timer.stop()
        if isValid(self.subscription_retry):self.subscription_retry.stop()
        if isValid(self.process):
            self.process.errorOccurred.disconnect(); self.process.finished.disconnect()
            self.process.closeWriteChannel()
            if self.process.state()!=QProcess.ProcessState.NotRunning:self.process.waitForFinished(50)
        if self.job:self.job.close();self.job=None
        if isValid(self.process) and self.process.state()!=QProcess.ProcessState.NotRunning:
            self.process.kill();self.process.waitForFinished(250)
        result={}
        if self.task_id:result['task_id']=self.task_id
        if self.task_cancelled is not None:result['task_cancelled']=self.task_cancelled
        self.shutdown_finished.emit(result)

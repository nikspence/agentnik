"""Bridge a coding worker to one explicitly selected MCP server."""
import copy
import queue
import threading
import uuid
from PySide6.QtCore import QObject, Signal, Slot
from .mcp_local import LocalSession
from .mcp_support import resolve_environment_references,server_timeout


class CodingMCPBridge(QObject):
    request_signal = Signal(object)
    close_signal = Signal()
    cleanup_finished = Signal(object)

    def __init__(self, server, config, parent=None):
        super().__init__(parent)
        self.server = copy.deepcopy(server); self.config = config
        self.environment_values={};self.environment_error=''
        if self.server.get('transport')!='http':
            try:self.environment_values=resolve_environment_references(self.server.get('env',{}))
            except ValueError:self.environment_error='A configured MCP environment variable is missing or invalid.'
        self.cache_scope = None;self.cache_partition=uuid.uuid4().hex
        self.session = None; self.pending = None; self.closed = False; self.identity = None; self.uncertain = False;self.elicitation_dialog=None
        self.request_signal.connect(self._dispatch); self.close_signal.connect(self.close)

    def request(self, action, payload, runtime):
        request = {'action': action, 'payload': payload, 'done': threading.Event(), 'cancelled': threading.Event(),'progress':queue.Queue(maxsize=40)}
        self.request_signal.emit(request)
        def drain_progress():
            while True:
                try:detail=request['progress'].get_nowait()
                except queue.Empty:return
                callback=getattr(runtime,'mcp_progress',None)
                if callable(callback):callback(self.server['name'],detail)
                else:
                    callback=getattr(runtime,'notify',None)
                    if callable(callback):callback('mcp','MCP '+self.server['name']+': '+detail)
        try:
            while not request['done'].wait(.05):drain_progress();runtime.check()
            drain_progress()
            runtime.check()
            return request['result']
        except BaseException:
            request['cancelled'].set(); self.close_signal.emit(); raise

    @Slot(object)
    def _dispatch(self, request):
        if request['cancelled'].is_set(): return
        if self.closed or self.server not in self.config.get('mcp_servers', []):
            self._reply(request, {'error':'Selected MCP server changed or is unavailable.'}); return
        if self.pending:
            self._reply(request, {'error':'MCP session is busy.'}); return
        self.pending = request
        if self.server.get('transport')=='http':
            self._remote(request); return
        if request['action'] == 'discover':
            if self.session:
                self._reply(request, {'error':'MCP session already started.'}); return
            if self.environment_error:self._reply(request, {'error':self.environment_error});return
            try:self.session = LocalSession(self.server['command'], self.server['args'], self,env_values=self.environment_values,timeout_seconds=server_timeout(self.server),working_directory=self.server.get('working_directory',''))
            except ValueError:self._reply(request, {'error':'MCP working directory or timeout is invalid on this system.'});return
            self.session.elicitation_enabled=True;self.session.elicitation_requested.connect(self._elicitation)
            self.session.discovered.connect(self._discovered); self.session.called.connect(self._called); self.session.ended.connect(self._ended);self.session.resources.connect(self._called);self.session.prompts.connect(self._called);self.session.progress.connect(self._progress);self.session.shutdown_finished.connect(self._cleanup);self.session.shutdown_finished.connect(lambda _result,session=self.session:session.deleteLater())
            self.session.start()
        elif request['action'] in ('prompts_list','prompts_get') and self.session:
            if not self.session.list_prompts(request['payload'] if request['action']=='prompts_get' else None):self._reply(request, {'error':'MCP prompts unavailable or invalid.'})
        elif request['action']=='complete' and self.session:
            payload=request['payload']
            if not self.session.complete_argument(payload['kind'],payload['target'],payload['argument'],payload['value'],payload['context']):self._reply(request, {'error':'MCP completion unavailable or invalid.'})
        elif request['action'] in ('templates_list','templates_read') and self.session:
            payload=request['payload'];ok=self.session.list_resource_templates() if request['action']=='templates_list' else self.session.read_resource_template(payload['template'],payload['arguments'],payload['uri'])
            if not ok:self._reply(request, {'error':'MCP resource template unavailable or invalid.'})
        elif request['action'] in ('resources_list','resources_read') and self.session:
            ok=self.session.list_resources() if request['action']=='resources_list' else self.session.read_resource(request['payload']['uri'])
            if not ok:self._reply(request, {'error':'MCP resources unavailable or not discovered.'})
        elif request['action'] == 'verify' and self.session:
            if not self.session.verify_tool(request['payload']['tool']):self._reply(request, {'error':'MCP session is no longer available.'})
        elif request['action'] == 'call' and self.session:
            payload=request['payload']
            if not self.session.call(payload['tool'],payload['arguments']): self._reply(request, {'error':'MCP session is no longer available.'})
        else:self._reply(request, {'error':'MCP session is unavailable.'})

    def _remote(self, request):
        action=request['action']
        if self.uncertain:
            self._reply(request, {'error':'A prior MCP call has an uncertain outcome; inspect server state before starting another run.'}); return
        if action=='discover':
            if self.session:
                self._reply(request, {'error':'MCP session already started.'}); return
            if self.server.get('auth_type')=='oauth':
                from .mcp_oauth_credentials import oauth_credential_broker
                oauth_credential_broker().request(self.server,lambda value:self._oauth_ready(request,value),lambda:self.server in self.config.get('mcp_servers',[]))
                return
            token=''
            if self.server['credential_id']:
                try:
                    import keyring
                    token=keyring.get_password('Agentnik',self.server['credential_id']) or ''
                except Exception:token=''
                if not token or len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token):
                    self._reply(request, {'error':'MCP credential is unavailable or invalid.'}); return
            self._start_remote(token);return
        if action in ('prompts_list','prompts_get') and self.session:
            if not self.session.list_prompts(request['payload'] if action=='prompts_get' else None):self._reply(request, {'error':'MCP prompts unavailable or invalid.'})
            return
        if action=='complete' and self.session:
            payload=request['payload']
            if not self.session.complete_argument(payload['kind'],payload['target'],payload['argument'],payload['value'],payload['context']):self._reply(request, {'error':'MCP completion unavailable or invalid.'})
            return
        if action in ('templates_list','templates_read') and self.session:
            payload=request['payload'];ok=self.session.list_resource_templates() if action=='templates_list' else self.session.read_resource_template(payload['template'],payload['arguments'],payload['uri'])
            if not ok:self._reply(request, {'error':'MCP resource template unavailable or invalid.'})
            return
        if action in ('resources_list','resources_read') and self.session:
            ok=self.session.list_resources() if action=='resources_list' else self.session.read_resource(request['payload']['uri'])
            if not ok:self._reply(request, {'error':'MCP resources unavailable or not discovered.'})
            return
        if action=='verify' and self.session:
            if not self.session.verify_tool(request['payload']['tool']):self._reply(request, {'error':'MCP session is no longer available.'})
            return
        if action=='call' and self.session:
            payload=request['payload']
            import json
            token=self.session.token
            if token and token in json.dumps(payload['arguments'],ensure_ascii=False):
                self._reply(request, {'error':'MCP arguments contain the configured credential.'}); return
            if not self.session.call(payload['tool'],payload['arguments']):
                self._reply(request, {'error':'MCP session is no longer available.'})
            return
        self._reply(request, {'error':'MCP session is unavailable; discover the server first.'})

    def _oauth_ready(self,request,result):
        if self.closed or self.pending is not request or request['cancelled'].is_set():return
        if self.server not in self.config.get('mcp_servers',[]):self._reply(request,{'error':'Selected MCP server changed or is unavailable.'});return
        if 'error' in result:self._reply(request,result);return
        self._start_remote(result['token'])

    def _start_remote(self,token):
        from .mcp_remote import RemoteSession
        session=RemoteSession(self.server['url'],token,self,timeout_seconds=server_timeout(self.server));self.session=session
        session.elicitation_enabled=True;session.elicitation_requested.connect(self._elicitation)
        session.discovered.connect(self._discovered);session.called.connect(self._called);session.ended.connect(self._ended);session.resources.connect(self._called);session.prompts.connect(self._called);session.progress.connect(self._progress)
        session.finished.connect(self._cleanup);session.finished.connect(lambda _result:session.deleteLater());session.start()

    def _reply(self, request, result):
        if self.pending is request:self.pending=None
        request['result']=result; request['done'].set()

    def _discovered(self, result):
        from . import search_cache
        token=getattr(self.session,'token','')
        identity={key:result.get(key) for key in ('name','version','protocol')}
        if result.get('protocol')=='2026-07-28' and result.get('server_identity_reported') is not True:identity['connection']=self.cache_partition
        self.cache_scope=search_cache.key(self.server,self.environment_values,token,identity).hex()
        if self.pending:self._reply(self.pending, result)
    def _called(self, result):
        if self.pending:self._reply(self.pending, result)

    def _progress(self,detail):
        request=self.pending
        if not request or request['cancelled'].is_set():return
        try:request['progress'].put_nowait(detail)
        except queue.Full:pass
    def _ended(self, result):
        self._close_elicitation()
        self.session=None
        if result.get('call_uncertain'):self.uncertain=True
        if self.pending:self._reply(self.pending, result)

    def _elicitation(self,forms):
        if self.closed or self.pending is None or self.pending['cancelled'].is_set() or self.session is None:return
        from PySide6.QtWidgets import QWidget,QDialog
        from .mcp_elicitation import ElicitationDialog
        parent=self.parent()
        while parent is not None and not isinstance(parent,QWidget):parent=parent.parent()
        session=self.session;dialog=ElicitationDialog(self.server['name'],forms,parent);self.elicitation_dialog=dialog
        def finished(code):
            if self.elicitation_dialog is not dialog:return
            self.elicitation_dialog=None;dialog.deleteLater()
            if self.closed or self.session is not session or self.pending is None or self.pending['cancelled'].is_set():return
            if code==QDialog.DialogCode.Accepted:session.continue_elicitation(dialog.responses)
            elif hasattr(session,'fail'):session.fail('MCP input request cancelled; the request was not continued.')
            else:session.stop('MCP input request cancelled; the request was not continued.')
        dialog.finished.connect(finished);dialog.open()

    def _close_elicitation(self):
        dialog=self.elicitation_dialog;self.elicitation_dialog=None
        if dialog:dialog.blockSignals(True);dialog.reject();dialog.deleteLater()

    def _cleanup(self,result):
        if isinstance(result,dict) and isinstance(result.get('task_id'),str):
            self.cleanup_finished.emit({'server':self.server['name'],'task_id':result['task_id'],'task_cancelled':result.get('task_cancelled')})

    @Slot()
    def close(self):
        if self.closed:return
        self.closed=True
        self._close_elicitation()
        if self.session:
            session=self.session;self.session=None
            if self.server.get('transport')=='http':session.shutdown()
            else:session.close()
        if self.pending:self._reply(self.pending, {'error':'MCP session closed; an in-flight call may have completed.', 'call_uncertain':True})

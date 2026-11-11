"""Bridge a coding worker to one explicitly selected Qt stdio MCP session."""
import copy
import threading
from PySide6.QtCore import QObject, Signal, Slot
from .mcp_local import LocalSession


class CodingMCPBridge(QObject):
    request_signal = Signal(object)
    close_signal = Signal()

    def __init__(self, server, config, parent=None):
        super().__init__(parent)
        self.server = copy.deepcopy(server); self.config = config
        self.session = None; self.pending = None; self.closed = False
        self.request_signal.connect(self._dispatch); self.close_signal.connect(self.close)

    def request(self, action, payload, runtime):
        request = {'action': action, 'payload': payload, 'done': threading.Event(), 'cancelled': threading.Event()}
        self.request_signal.emit(request)
        try:
            while not request['done'].wait(.05): runtime.check()
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
        if request['action'] == 'discover':
            if self.session:
                self._reply(request, {'error':'MCP session already started.'}); return
            self.session = LocalSession(self.server['command'], self.server['args'], self)
            self.session.discovered.connect(self._discovered); self.session.called.connect(self._called); self.session.ended.connect(self._ended)
            self.session.start()
        elif request['action'] == 'call' and self.session:
            payload=request['payload']
            if not self.session.call(payload['tool'],payload['arguments']): self._reply(request, {'error':'MCP session is no longer available.'})
        else:self._reply(request, {'error':'MCP session is unavailable.'})

    def _reply(self, request, result):
        if self.pending is request:self.pending=None
        request['result']=result; request['done'].set()

    def _discovered(self, result):
        if self.pending:self._reply(self.pending, result)
    def _called(self, result):
        if self.pending:self._reply(self.pending, result)
    def _ended(self, result):
        self.session=None
        if self.pending:self._reply(self.pending, result)

    @Slot()
    def close(self):
        if self.closed:return
        self.closed=True
        if self.session:self.session.close();self.session.deleteLater();self.session=None
        if self.pending:self._reply(self.pending, {'error':'MCP session closed; an in-flight call may have completed.', 'call_uncertain':True})

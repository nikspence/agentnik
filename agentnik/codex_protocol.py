"""Fixture-ready Codex app-server protocol adapter; no launcher or credentials."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from . import __version__


class ProtocolError(ValueError):pass


@dataclass(frozen=True)
class ApprovalRequest:
    request_id:object
    payload:str

    @property
    def fingerprint(self):return hashlib.sha256(self.payload.encode()).hexdigest()


class AppServerProtocol:
    MAX_MESSAGE=32_000
    MAX_TOTAL=256_000
    def __init__(self,send,emit):
        self.send=send;self.emit=emit;self.ready=False;self.closed=False
        self.thread_id=self.turn_id=self.cwd=None;self.pending={};self.seen=set();self.items={};self.total=0

    def initialize(self):
        if self.closed or self.ready or getattr(self,'initializing',False):raise ProtocolError('Invalid initialization state')
        self.initializing=True
        self.send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'agentnik','version':__version__},'capabilities':{'experimentalApi':False}}})

    def activate(self,thread_id,turn_id,cwd):
        # IDs must come from a future explicit start/resume controller, never history auto-play.
        if not self.ready or self.closed or self.pending:raise ProtocolError('Adapter is not ready for a turn')
        if not all(isinstance(v,str) and 0<len(v)<=200 for v in (thread_id,turn_id)):raise ProtocolError('Invalid conversation identity')
        try:path=Path(cwd).resolve(strict=True)
        except (OSError,ValueError,TypeError):raise ProtocolError('Invalid working directory') from None
        if not path.is_dir():raise ProtocolError('Invalid working directory')
        self.thread_id=thread_id;self.turn_id=turn_id;self.cwd=str(path);self.items={}

    def _reject(self,ident):
        self.send({'id':ident,'result':{'decision':'decline'}})
        self.emit({'kind':'approval_rejected','text':'Request is outside the supported command approval contract.'})

    def receive(self,line):
        try:return self._receive(line)
        except (ValueError,TypeError,KeyError,AttributeError,OSError,RecursionError):
            self.close();raise ProtocolError("Invalid app-server message; adapter closed") from None

    def _receive(self,line):
        if self.closed:raise ProtocolError('Adapter closed')
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ProtocolError('Duplicate protocol field')
                value[key]=item
            return value
        if not isinstance(line,(str,bytes)):raise ProtocolError('Expected a JSON line')
        size=len(line.encode() if isinstance(line,str) else line);self.total+=size
        if size>self.MAX_MESSAGE or self.total>self.MAX_TOTAL:
            self.close();raise ProtocolError('App-server output budget exceeded')
        try:message=json.loads(line,object_pairs_hook=unique)
        except (ValueError,UnicodeError,RecursionError):raise ProtocolError('Malformed app-server JSON') from None
        if not isinstance(message,dict):raise ProtocolError('Malformed app-server message')
        if 'method' not in message:
            if not getattr(self,'initializing',False) or self.ready or message.get('id')!=1 or not isinstance(message.get('result'),dict) or 'error' in message:
                raise ProtocolError('Unexpected app-server response')
            self.ready=True;self.send({'method':'initialized','params':{}});return
        if not self.ready:raise ProtocolError('Notification before initialization')
        method=message['method'];params=message.get('params',{})
        if not isinstance(method,str) or len(method)>256:raise ProtocolError('Invalid method')
        if not isinstance(params,dict):raise ProtocolError('Malformed event parameters')
        scoped=params.get('threadId')==self.thread_id and params.get('turnId')==self.turn_id and self.turn_id is not None
        if 'id' in message:
            ident=message['id']
            if type(ident) not in (str,int) or ident in self.seen or len(self.seen)>=128:raise ProtocolError('Invalid or repeated server request ID')
            self.seen.add(ident)
            if method!='item/commandExecution/requestApproval':
                self.send({'id':ident,'error':{'code':-32601,'message':'Unsupported server request'}});return
            if not scoped:return self._reject(ident)
            item=self.items.get(params.get('itemId'),{})
            command=params.get('command') or item.get('command');cwd=params.get('cwd') or item.get('cwd')
            unsupported=set(params)-{'threadId','turnId','itemId','reason','command','cwd','commandActions','proposedExecpolicyAmendment','availableDecisions','networkApprovalContext','additionalPermissions'}
            if (unsupported or params.get('networkApprovalContext') is not None or params.get('additionalPermissions') is not None
                or not isinstance(command,str) or not command or len(command)>4096 or not isinstance(cwd,str)):
                return self._reject(ident)
            if not item or item.get('type')!='commandExecution' or item.get('command')!=command or item.get('cwd')!=cwd:return self._reject(ident)
            try:matches=str(Path(cwd).resolve(strict=True))==self.cwd
            except (OSError,ValueError):matches=False
            if not matches:return self._reject(ident)
            if 'availableDecisions' in params and not isinstance(params['availableDecisions'],list):return self._reject(ident)
            if self.pending or len(params.get('reason','') or '')>4096:return self._reject(ident)
            payload=json.dumps({'requestId':ident,'params':params,'command':command,'cwd':cwd},sort_keys=True,separators=(',',':'))
            proposal=ApprovalRequest(ident,payload);self.pending[ident]=proposal
            self.emit({'kind':'approval','request_id':ident,'fingerprint':proposal.fingerprint,'command':command,'cwd':cwd,
                       'recommendation':'Not checked; no System One review performed'})
        elif scoped and method=='item/started':
            item=params.get('item')
            if not isinstance(item,dict) or not isinstance(item.get('id'),str):raise ProtocolError('Malformed item')
            if len(self.items)>=64 or item['id'] in self.items:raise ProtocolError('Duplicate or excessive items')
            self.items[item['id']]=item
        elif method=='serverRequest/resolved':
            self.pending.pop(params.get('requestId'),None)
        elif scoped and method=='turn/completed':
            self.pending.clear();self.turn_id=None;self.emit({'kind':'turn_completed'})
        elif scoped and method=='item/completed':
            item=params.get('item',{});ident=item.get('id')
            for request_id,proposal in list(self.pending.items()):
                if json.loads(proposal.payload)['params'].get('itemId')==ident:self.pending.pop(request_id,None)
            self.emit({'kind':'item_completed'})
        # Unknown notifications carry no permission to execute and are ignored.

    def decide(self,request_id,fingerprint,accept=False):
        proposal=self.pending.get(request_id)
        if self.closed or proposal is None or proposal.fingerprint!=fingerprint or type(accept) is not bool:return False
        params=json.loads(proposal.payload)['params']
        if params.get('threadId')!=self.thread_id or params.get('turnId')!=self.turn_id:return False
        if accept and 'availableDecisions' in params and 'accept' not in params['availableDecisions']:return False
        self.pending.pop(request_id)
        self.send({'id':request_id,'result':{'decision':'accept' if accept else 'decline'}});return True

    def close(self):
        # Transport/process shutdown is a separate, still unimplemented boundary.
        self.closed=True;self.pending.clear();self.items.clear();self.turn_id=None

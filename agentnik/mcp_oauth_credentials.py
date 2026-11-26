"""Keyring-only MCP OAuth credential records and one-shot refresh requests."""
from urllib.parse import urlencode
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
from . import tls
from .mcp_oauth import parse_token_response,_MAX_RESPONSE
from .mcp_oauth_record import validate_record,make_record,read_record,write_record,credential_state,oauth_refresh_lease
from .mcp_support import server_timeout

class OAuthRefresh(QObject):
    """Make one refresh request; never automatically repeat an uncertain exchange."""
    finished=Signal(object)
    def __init__(self,record,parent=None,manager=None,timeout_ms=15000):
        super().__init__(parent);self.record=validate_record(record);self.manager=manager or QNetworkAccessManager(self);self.reply=None;self.buffer=bytearray();self.closed=False;self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.stop('OAuth refresh timed out. Sign in again.'));self.timeout_ms=timeout_ms

    def start(self):
        if not self.record['refresh_token']:self.stop('OAuth credential expired. Sign in again.');return
        request=QNetworkRequest(QUrl(self.record['token_endpoint']));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy);request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,QNetworkRequest.LoadControl.Manual);request.setRawHeader(b'Accept',b'application/json');request.setRawHeader(b'Content-Type',b'application/x-www-form-urlencoded');tls.configure_qt_request(request)
        body=urlencode({'grant_type':'refresh_token','client_id':self.record['client_id'],'refresh_token':self.record['refresh_token'],'resource':self.record['resource_url']}).encode('ascii')
        self.timer.start(self.timeout_ms);self.reply=self.manager.post(request,body);self.reply.setReadBufferSize(_MAX_RESPONSE+1)
        if tls.relaxed():self.reply.sslErrors.connect(lambda _errors,reply=self.reply:reply.ignoreSslErrors())
        self.reply.readyRead.connect(self.read);self.reply.finished.connect(self.received)

    def read(self):
        if not self.reply:return
        self.buffer.extend(bytes(self.reply.readAll()))
        if len(self.buffer)>_MAX_RESPONSE:self.stop('OAuth refresh response exceeded the size limit. Sign in again.')

    def received(self):
        reply=self.reply
        if reply is None:return
        self.read()
        if self.reply is not reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute);ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower();self.reply=None;reply.deleteLater()
        try:
            result=parse_token_response(self.buffer,status,ctype);old=self.record
            updated=make_record(old['resource_url'],old['issuer'],old['token_endpoint'],old['client_id'],result,previous_refresh=old['refresh_token'],client_id_expires_at=old.get('client_id_expires_at'))
            self.closed=True;self.timer.stop();self.record=None;self.buffer.clear();self.finished.emit({'credential':updated})
        except (ValueError,TypeError,UnicodeError,RecursionError):self.stop('OAuth refresh failed or returned an invalid token. Sign in again.')

    def stop(self,message='OAuth refresh cancelled. Sign in again.'):
        if self.closed:return
        self.closed=True;self.timer.stop();reply=self.reply;self.reply=None
        if reply:reply.abort();reply.deleteLater()
        self.record=None;self.buffer.clear();self.finished.emit({'error':message})


class OAuthCredentialBroker(QObject):
    """Serialize refreshes of a rotating credential across active MCP sessions."""
    def __init__(self,parent=None,refresh_factory=OAuthRefresh,lock_factory=oauth_refresh_lease):
        super().__init__(parent);self.refresh_factory=refresh_factory;self.lock_factory=lock_factory;self.pending={}

    @staticmethod
    def current(check):
        try:return bool(check())
        except Exception:return False

    def request(self,server,callback,is_current):
        if not self.current(is_current):callback({'error':'Selected MCP server changed or is unavailable.'});return
        ident=server.get('credential_id');resource=server.get('url')
        if server.get('auth_type')!='oauth' or not ident:callback({'error':'OAuth credential is unavailable or invalid.'});return
        if ident in self.pending:
            pending=self.pending[ident]
            if pending['resource']!=resource:callback({'error':'OAuth credential does not match the MCP server.'});return
            pending['waiters'].append((callback,is_current));return
        try:record=read_record(ident,resource);state=credential_state(record)
        except Exception:callback({'error':'OAuth credential is unavailable or invalid. Sign in again.'});return
        if state=='ready':callback({'token':record['access_token']});return
        if state=='uncertain':callback({'error':'OAuth refresh outcome is uncertain. Sign in again.'});return
        if state=='expired':callback({'error':'OAuth credential expired. Sign in again.'});return
        try:lease=self.lock_factory(ident)
        except Exception:callback({'error':'Could not reserve the OAuth credential for refresh. Try again later.'});return
        marked=dict(record,refresh_pending=True)
        try:
            if read_record(ident,resource)!=record:raise ValueError('OAuth credential changed')
            write_record(ident,marked)
        except Exception:lease.close();callback({'error':'Could not prepare the OAuth credential for refresh. Sign in again.'});return
        try:job=self.refresh_factory(record,self,timeout_ms=server_timeout(server)*1000)
        except Exception:lease.close();callback({'error':'Could not start OAuth refresh. Sign in again.'});return
        pending={'resource':resource,'record':marked,'job':job,'lease':lease,'waiters':[(callback,is_current)]};self.pending[ident]=pending
        job.finished.connect(lambda result,ident=ident,job=job:self.refreshed(ident,job,result))
        try:job.start()
        except Exception:self.refreshed(ident,job,{'error':'OAuth refresh failed. Sign in again.'})

    def refreshed(self,ident,job,result):
        pending=self.pending.get(ident)
        if not pending or pending['job'] is not job:return
        del self.pending[ident];job.deleteLater();waiters=pending['waiters'];active=any(self.current(check) for _,check in waiters)
        outcome={'error':'OAuth refresh failed. Sign in again.'}
        if active and 'credential' in result:
            try:
                if read_record(ident,pending['resource'])!=pending['record']:raise ValueError('OAuth credential changed')
                record=validate_record(result['credential'],pending['resource']);write_record(ident,record);outcome={'token':record['access_token']}
            except Exception:outcome={'error':'Could not save the refreshed OAuth credential. Sign in again.'}
        pending['lease'].close()
        for callback,check in waiters:
            callback(outcome if self.current(check) else {'error':'Selected MCP server changed or is unavailable.'})


_broker=None


def oauth_credential_broker():
    from PySide6.QtCore import QCoreApplication
    global _broker
    if _broker is not None:
        try:_broker.thread()
        except RuntimeError:_broker=None
    if _broker is None:_broker=OAuthCredentialBroker(QCoreApplication.instance())
    return _broker

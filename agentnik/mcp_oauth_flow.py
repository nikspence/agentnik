"""Browser-based MCP OAuth authorization with PKCE and a loopback callback."""
import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs,parse_qsl,urlencode,urlsplit,urlunsplit
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QHostAddress,QNetworkAccessManager,QNetworkRequest,QTcpServer
from . import tls
from .mcp_oauth import _https_parts
from .mcp_oauth_discovery import _object_pairs

_RESERVED=frozenset(('client_id','response_type','redirect_uri','state','scope','resource','code_challenge','code_challenge_method','grant_type','code','code_verifier'))
_MAX_RESPONSE=65536


def parse_token_response(data,status,ctype):
    """Validate token material without exposing server-provided error text."""
    if status!=200 or ctype!='application/json':raise ValueError('Invalid token response')
    result=json.loads(bytes(data).decode('utf-8'),object_pairs_hook=_object_pairs)
    if not isinstance(result,dict) or not isinstance(result.get('token_type'),str) or result['token_type'].lower()!='bearer':raise ValueError('Invalid token response')
    token=result.get('access_token')
    if not isinstance(token,str) or not token or len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token):raise ValueError('Invalid token response')
    refresh=result.get('refresh_token')
    if refresh is not None and (not isinstance(refresh,str) or not refresh or len(refresh)>4096 or any(not 33<=ord(ch)<=126 for ch in refresh)):raise ValueError('Invalid token response')
    expiry=result.get('expires_in')
    if expiry is not None and (type(expiry) is not int or expiry<=0):raise ValueError('Invalid token response')
    return {'access_token':token,'refresh_token':refresh,'expires_in':expiry}


def _endpoint(url):
    parts=_https_parts(url,allow_query=True)
    if any(key.lower() in _RESERVED for key,_ in parse_qsl(parts.query,keep_blank_values=True,max_num_fields=100)):raise ValueError('Reserved OAuth endpoint query parameter')
    return parts


def _scope(value):
    if not isinstance(value,str) or len(value)>4096 or any(ord(ch)<32 or ord(ch)>126 for ch in value):raise ValueError('Invalid OAuth scope')
    scopes=value.split()
    if any(not scope or any(ord(ch)<33 or ord(ch)>126 or ch in '"\\' for ch in scope) for scope in scopes):raise ValueError('Invalid OAuth scope')
    return ' '.join(scopes)


class OAuthAuthorization(QObject):
    """One authorization attempt; secrets are returned only in the finished signal."""
    finished=Signal(object)
    def __init__(self,resource_url,metadata,client_id,scopes='',parent=None,manager=None,open_url=None,timeout_ms=180000):
        super().__init__(parent);self.resource_url=resource_url;self.metadata=metadata;self.client_id=client_id;self.scopes=scopes;self.manager=manager or QNetworkAccessManager(self);self.open_url=open_url or QDesktopServices.openUrl;self.timeout_ms=timeout_ms
        self.listener=QTcpServer(self);self.listener.newConnection.connect(self.accept);self.sockets={};self.reply=None;self.buffer=bytearray();self.closed=False;self.state='';self.verifier='';self.redirect_uri=''
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.stop('OAuth authorization timed out.'))

    def start(self):
        try:
            resource=_https_parts(self.resource_url,allow_query=True);_endpoint(self.metadata['authorization_endpoint']);_endpoint(self.metadata['token_endpoint']);_https_parts(self.metadata['issuer'])
            if self.metadata.get('pkce_s256') is not True:raise ValueError('PKCE is unavailable')
            if not isinstance(self.client_id,str) or not self.client_id or len(self.client_id)>1024 or any(ord(ch)<33 or ord(ch)>126 for ch in self.client_id):raise ValueError('Invalid client ID')
            scope=_scope(self.scopes)
            self.resource=urlunsplit((resource.scheme,resource.netloc,resource.path,resource.query,''))
            if not self.listener.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost),0):raise ValueError('Loopback callback unavailable')
            self.redirect_uri='http://127.0.0.1:'+str(self.listener.serverPort())+'/callback'
            self.state=secrets.token_urlsafe(32);self.verifier=secrets.token_urlsafe(64)
            challenge=base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
            params={'response_type':'code','client_id':self.client_id,'redirect_uri':self.redirect_uri,'state':self.state,'code_challenge':challenge,'code_challenge_method':'S256','resource':self.resource}
            if scope:params['scope']=scope
            endpoint=urlsplit(self.metadata['authorization_endpoint']);query=endpoint.query+('&' if endpoint.query else '')+urlencode(params);url=urlunsplit((endpoint.scheme,endpoint.netloc,endpoint.path,query,''))
            self.timer.start(self.timeout_ms)
            if not self.open_url(QUrl(url)):self.stop('Could not open the browser for OAuth authorization.')
        except (KeyError,TypeError,ValueError):self.stop('OAuth authorization settings are invalid or PKCE is unavailable.')

    def accept(self):
        while self.listener.hasPendingConnections():
            sock=self.listener.nextPendingConnection()
            if len(self.sockets)>=4:sock.abort();sock.deleteLater();continue
            sock.setReadBufferSize(8193)
            self.sockets[sock]=bytearray();sock.readyRead.connect(lambda sock=sock:self.read_callback(sock));sock.disconnected.connect(lambda sock=sock:self.drop_socket(sock))

    def drop_socket(self,sock):
        self.sockets.pop(sock,None);sock.deleteLater()

    def answer(self,sock,success):
        body=b'Authorization received. You may close this window.' if success else b'Invalid authorization response.'
        status=b'200 OK' if success else b'400 Bad Request'
        sock.write(b'HTTP/1.1 '+status+b'\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body);sock.disconnectFromHost()

    def read_callback(self,sock):
        data=self.sockets.get(sock)
        if data is None:return
        data.extend(bytes(sock.readAll()))
        if len(data)>8192:self.answer(sock,False);return
        if b'\r\n\r\n' not in data:return
        try:
            lines=bytes(data).split(b'\r\n');method,target,version=lines[0].decode('ascii').split(' ')
            if method!='GET' or version not in ('HTTP/1.0','HTTP/1.1') or any(ord(ch)<33 or ord(ch)>126 for ch in target):raise ValueError()
            headers=[line.partition(b':') for line in lines[1:] if line]
            hosts=[value.strip().lower() for name,separator,value in headers if separator and name.lower()==b'host']
            if hosts!=[('127.0.0.1:'+str(self.listener.serverPort())).encode()]:raise ValueError()
            parts=urlsplit(target)
            if parts.scheme or parts.netloc or parts.path!='/callback' or parts.fragment:raise ValueError()
            values=parse_qs(parts.query,keep_blank_values=True,strict_parsing=True,max_num_fields=16)
            state=values.get('state',[''])[0]
            if any(len(items)!=1 for items in values.values()) or not self.state or not state.isascii() or not secrets.compare_digest(state,self.state):raise ValueError()
            if 'iss' in values and values['iss'][0]!=self.metadata['issuer']:raise ValueError()
            code=values.get('code',[''])[0]
            if 'error' in values:
                self.answer(sock,False);self.stop('OAuth authorization was declined or failed.');return
            if not code or len(code)>4096 or any(ord(ch)<33 or ord(ch)>126 for ch in code):raise ValueError()
        except (TypeError,ValueError,UnicodeError):self.answer(sock,False);return
        self.answer(sock,True);self.listener.close();self.state='';self.exchange(code)

    def exchange(self,code):
        request=QNetworkRequest(QUrl(self.metadata['token_endpoint']));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy);request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,QNetworkRequest.LoadControl.Manual);request.setRawHeader(b'Accept',b'application/json');request.setRawHeader(b'Content-Type',b'application/x-www-form-urlencoded');tls.configure_qt_request(request)
        data=urlencode({'grant_type':'authorization_code','client_id':self.client_id,'code':code,'redirect_uri':self.redirect_uri,'code_verifier':self.verifier,'resource':self.resource}).encode('ascii')
        self.reply=self.manager.post(request,data);self.reply.setReadBufferSize(_MAX_RESPONSE+1)
        if tls.relaxed():self.reply.sslErrors.connect(lambda _errors,reply=self.reply:reply.ignoreSslErrors())
        self.reply.readyRead.connect(self.read_token);self.reply.finished.connect(self.token_received)

    def read_token(self):
        if not self.reply:return
        self.buffer.extend(bytes(self.reply.readAll()))
        if len(self.buffer)>_MAX_RESPONSE:self.stop('OAuth token response exceeded the size limit.')

    def token_received(self):
        reply=self.reply
        if reply is None:return
        self.read_token()
        if self.reply is not reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute);ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower();self.reply=None;reply.deleteLater()
        try:
            result=parse_token_response(self.buffer,status,ctype)
            self.closed=True;self.timer.stop();self.verifier='';self.state='';self.buffer.clear();self.finished.emit(result)
        except (ValueError,TypeError,UnicodeError,RecursionError):self.stop('OAuth token exchange failed or returned an invalid token.')

    def stop(self,message='OAuth authorization cancelled.'):
        if self.closed:return
        self.closed=True;self.timer.stop();self.listener.close();reply=self.reply;self.reply=None
        if reply:reply.abort();reply.deleteLater()
        for sock in list(self.sockets):sock.abort();sock.deleteLater()
        self.sockets.clear();self.verifier='';self.state='';self.buffer.clear();self.finished.emit({'error':message})

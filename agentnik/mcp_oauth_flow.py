"""Browser-based MCP OAuth authorization with PKCE and a loopback callback."""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs,urlencode,urlsplit,urlunsplit
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QHostAddress,QNetworkAccessManager,QNetworkRequest,QTcpServer
from . import tls
from .mcp_oauth import _https_parts,_object_pairs,_endpoint,_MAX_RESPONSE,parse_token_response

def _scope(value):
    if not isinstance(value,str) or len(value)>4096 or any(ord(ch)<32 or ord(ch)>126 for ch in value):raise ValueError('Invalid OAuth scope')
    scopes=value.split()
    if any(not scope or any(ord(ch)<33 or ord(ch)>126 or ch in '"\\' for ch in scope) for scope in scopes):raise ValueError('Invalid OAuth scope')
    return ' '.join(scopes)


class OAuthAuthorization(QObject):
    """One authorization attempt; secrets are returned only in the finished signal."""
    finished=Signal(object)
    def __init__(self,resource_url,metadata,client_id,scopes='',parent=None,manager=None,open_url=None,timeout_ms=180000):
        super().__init__(parent);self.resource_url=resource_url;self.metadata=metadata;self.client_id=client_id;self.dynamic=client_id is None or client_id=='';self.scopes=scopes;self.manager=manager or QNetworkAccessManager(self);self.open_url=open_url or QDesktopServices.openUrl;self.timeout_ms=timeout_ms
        self.listener=QTcpServer(self);self.listener.newConnection.connect(self.accept);self.sockets={};self.reply=None;self.buffer=bytearray();self.closed=False;self.state='';self.verifier='';self.redirect_uri='';self.client_id_expires_at=None
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.stop('OAuth authorization timed out.'))

    def start(self):
        try:
            resource=_https_parts(self.resource_url,allow_query=True);_endpoint(self.metadata['authorization_endpoint']);_endpoint(self.metadata['token_endpoint']);_https_parts(self.metadata['issuer'])
            if self.metadata.get('pkce_s256') is not True or self.metadata.get('public_client_supported',True) is not True:raise ValueError('PKCE or public client authentication is unavailable')
            if self.dynamic:_endpoint(self.metadata['registration_endpoint'])
            elif not isinstance(self.client_id,str) or len(self.client_id)>1024 or any(ord(ch)<33 or ord(ch)>126 for ch in self.client_id):raise ValueError('Invalid client ID')
            self.scopes=_scope(self.scopes)
            self.resource=urlunsplit((resource.scheme,resource.netloc,resource.path,resource.query,''))
            if not self.listener.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost),0):raise ValueError('Loopback callback unavailable')
            self.redirect_uri='http://127.0.0.1:'+str(self.listener.serverPort())+'/callback'
            self.state=secrets.token_urlsafe(32);self.verifier=secrets.token_urlsafe(64)
            self.timer.start(self.timeout_ms)
            if self.dynamic:self.register()
            else:self.open_authorization()
        except (KeyError,TypeError,ValueError):self.stop('OAuth authorization settings are invalid or PKCE is unavailable.')

    def register(self):
        request=QNetworkRequest(QUrl(self.metadata['registration_endpoint']));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy);request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,QNetworkRequest.LoadControl.Manual);request.setRawHeader(b'Accept',b'application/json');request.setRawHeader(b'Content-Type',b'application/json');tls.configure_qt_request(request)
        grants=['authorization_code']+(['refresh_token'] if self.metadata.get('refresh_grant_supported') is True else [])
        body=json.dumps({'client_name':'Agentnik','application_type':'native','redirect_uris':[self.redirect_uri],'grant_types':grants,'response_types':['code'],'token_endpoint_auth_method':'none'},separators=(',',':')).encode('utf-8')
        self.buffer.clear();self.reply=self.manager.post(request,body);self.reply.setReadBufferSize(_MAX_RESPONSE+1)
        if tls.relaxed():self.reply.sslErrors.connect(lambda _errors,reply=self.reply:reply.ignoreSslErrors())
        self.reply.readyRead.connect(self.read_token);self.reply.finished.connect(self.registration_received)

    def registration_received(self):
        reply=self.reply
        if reply is None:return
        self.read_token()
        if self.reply is not reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute);ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower();self.reply=None;reply.deleteLater()
        try:
            if status not in (200,201) or ctype!='application/json':raise ValueError()
            result=json.loads(bytes(self.buffer).decode('utf-8'),object_pairs_hook=_object_pairs);self.buffer.clear()
            if not isinstance(result,dict):raise ValueError()
            client_id=result.get('client_id');expires=result.get('client_id_expires_at',0)
            if not isinstance(client_id,str) or not client_id or len(client_id)>1024 or any(ord(ch)<33 or ord(ch)>126 for ch in client_id):raise ValueError()
            if type(expires) is not int or expires<0 or (expires and expires<=int(time.time())):raise ValueError()
            if result.get('token_endpoint_auth_method','none')!='none' or result.get('client_secret'):raise ValueError()
            if 'redirect_uris' in result and result['redirect_uris']!=[self.redirect_uri]:raise ValueError()
            if 'grant_types' in result and (not isinstance(result['grant_types'],list) or 'authorization_code' not in result['grant_types']):raise ValueError()
            if 'response_types' in result and (not isinstance(result['response_types'],list) or 'code' not in result['response_types']):raise ValueError()
            self.client_id=client_id;self.client_id_expires_at=expires or None;self.open_authorization()
        except (ValueError,TypeError,UnicodeError,RecursionError):self.stop('OAuth client registration failed or returned invalid metadata.')

    def open_authorization(self):
        challenge=base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        params={'response_type':'code','client_id':self.client_id,'redirect_uri':self.redirect_uri,'state':self.state,'code_challenge':challenge,'code_challenge_method':'S256','resource':self.resource}
        if self.scopes:params['scope']=self.scopes
        endpoint=urlsplit(self.metadata['authorization_endpoint']);query=endpoint.query+('&' if endpoint.query else '')+urlencode(params);url=urlunsplit((endpoint.scheme,endpoint.netloc,endpoint.path,query,''))
        if not self.open_url(QUrl(url)):self.stop('Could not open the browser for OAuth authorization.')

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
            if self.metadata.get('authorization_response_iss_parameter_supported') is True and 'iss' not in values:raise ValueError()
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
        if len(self.buffer)>_MAX_RESPONSE:self.stop('OAuth client registration response exceeded the size limit.' if self.dynamic and not self.client_id else 'OAuth token response exceeded the size limit.')

    def token_received(self):
        reply=self.reply
        if reply is None:return
        self.read_token()
        if self.reply is not reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute);ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower();self.reply=None;reply.deleteLater()
        try:
            result=parse_token_response(self.buffer,status,ctype)
            if self.dynamic:
                result['client_id']=self.client_id
                if self.client_id_expires_at is not None:result['client_id_expires_at']=self.client_id_expires_at
            self.closed=True;self.timer.stop();self.verifier='';self.state='';self.buffer.clear();self.finished.emit(result)
        except (ValueError,TypeError,UnicodeError,RecursionError):self.stop('OAuth token exchange failed or returned an invalid token.')

    def stop(self,message='OAuth authorization cancelled.'):
        if self.closed:return
        self.closed=True;self.timer.stop();self.listener.close();reply=self.reply;self.reply=None
        if reply:reply.abort();reply.deleteLater()
        for sock in list(self.sockets):sock.abort();sock.deleteLater()
        self.sockets.clear();self.verifier='';self.state='';self.buffer.clear();self.finished.emit({'error':message})

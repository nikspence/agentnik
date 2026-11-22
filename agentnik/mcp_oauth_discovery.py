"""Asynchronous, bounded discovery for remote MCP authorization metadata."""
import json
from urllib.parse import urlsplit
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
from . import tls
from .mcp_oauth import _https_parts,protected_resource_metadata_urls,authorization_server_metadata_urls

MAX_METADATA=131072


def _object_pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate metadata field')
        result[key]=value
    return result


def _same_resource(configured,claimed):
    configured=urlsplit(configured);claimed=urlsplit(claimed)
    if (configured.scheme.lower(),configured.hostname.lower(),configured.port or 443)!=(claimed.scheme.lower(),claimed.hostname.lower(),claimed.port or 443):return False
    resource_path=claimed.path.rstrip('/')
    return (not resource_path or configured.path==resource_path or configured.path.startswith(resource_path+'/')) and (not claimed.query or claimed.query==configured.query)


def parse_resource_metadata(document,resource_url):
    if not isinstance(document,dict):raise ValueError('Invalid protected resource metadata')
    _https_parts(resource_url,allow_query=True)
    resource=document.get('resource');_https_parts(resource,allow_query=True)
    if not _same_resource(resource_url,resource):raise ValueError('Protected resource metadata does not match the MCP server')
    issuers=document.get('authorization_servers')
    if not isinstance(issuers,list) or not 1<=len(issuers)<=20 or len(set(issuers))!=len(issuers):raise ValueError('Invalid authorization server list')
    for issuer in issuers:_https_parts(issuer)
    scopes=document.get('scopes_supported',[])
    if not isinstance(scopes,list) or len(scopes)>100 or any(not isinstance(s,str) or not s or len(s)>256 or any(ord(ch)<33 or ord(ch)>126 or ch in '"\\' for ch in s) for s in scopes):raise ValueError('Invalid OAuth scopes')
    return {'resource':resource,'issuers':issuers,'scopes_supported':scopes}


def parse_authorization_metadata(document,issuer):
    if not isinstance(document,dict) or document.get('issuer')!=issuer:raise ValueError('OAuth issuer does not match its metadata')
    authorization=document.get('authorization_endpoint');token=document.get('token_endpoint')
    _https_parts(authorization,allow_query=True);_https_parts(token,allow_query=True)
    methods=document.get('code_challenge_methods_supported',[])
    if not isinstance(methods,list) or any(not isinstance(value,str) for value in methods):raise ValueError('Invalid PKCE metadata')
    auth_methods=document.get('token_endpoint_auth_methods_supported')
    if auth_methods is not None and (not isinstance(auth_methods,list) or any(not isinstance(value,str) for value in auth_methods)):raise ValueError('Invalid OAuth client authentication metadata')
    grants=document.get('grant_types_supported',[])
    if not isinstance(grants,list) or any(not isinstance(value,str) for value in grants):raise ValueError('Invalid OAuth grant metadata')
    registration=document.get('registration_endpoint')
    if registration is not None:_https_parts(registration,allow_query=True)
    return {'issuer':issuer,'authorization_endpoint':authorization,'token_endpoint':token,'registration_endpoint':registration,'pkce_s256':'S256' in methods,'public_client_supported':auth_methods is None or 'none' in auth_methods,'refresh_grant_supported':'refresh_token' in grants}


class OAuthMetadataDiscovery(QObject):
    finished=Signal(object)
    def __init__(self,resource_url,challenge=None,parent=None,manager=None,timeout_ms=15000):
        super().__init__(parent);self.resource_url=resource_url;self.challenge=challenge or {};self.manager=manager or QNetworkAccessManager(self);self.reply=None;self.data=bytearray();self.phase='resource';self.resource=None;self.issuer=None;self.urls=[];self.issuers=[];self.closed=False
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.stop('OAuth discovery timed out.'));self.timeout_ms=timeout_ms

    def start(self):
        try:self.urls=protected_resource_metadata_urls(self.resource_url,self.challenge)
        except (TypeError,ValueError):self.stop('Invalid OAuth resource metadata URL.');return
        self.timer.start(self.timeout_ms);self.next_url()

    def next_url(self):
        if not self.urls:
            if self.phase=='issuer' and self.issuers:
                self.issuer=self.issuers.pop(0);self.urls=authorization_server_metadata_urls(self.issuer)
            else:self.stop('OAuth metadata could not be discovered.');return
        url=self.urls.pop(0);request=QNetworkRequest(QUrl(url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy);request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,QNetworkRequest.LoadControl.Manual);request.setRawHeader(b'Accept',b'application/json');tls.configure_qt_request(request)
        self.data=bytearray();self.reply=self.manager.get(request);self.reply.setReadBufferSize(MAX_METADATA+1)
        if tls.relaxed():self.reply.sslErrors.connect(lambda _errors,reply=self.reply:reply.ignoreSslErrors())
        self.reply.readyRead.connect(self.read);self.reply.finished.connect(self.received)

    def read(self):
        if not self.reply:return
        self.data.extend(bytes(self.reply.readAll()))
        if len(self.data)>MAX_METADATA:self.stop('OAuth metadata exceeded the size limit.')

    def received(self):
        reply=self.reply
        if reply is None:return
        self.read()
        if self.reply is not reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute);ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower();self.reply=None;reply.deleteLater()
        if status in (404,405):self.next_url();return
        if status!=200 or ctype!='application/json':self.stop('OAuth metadata request failed.');return
        try:
            document=json.loads(bytes(self.data).decode('utf-8'),object_pairs_hook=_object_pairs)
            if self.phase=='resource':
                self.resource=parse_resource_metadata(document,self.resource_url);self.issuers=list(self.resource['issuers']);self.phase='issuer';self.urls=[];self.next_url();return
            metadata=parse_authorization_metadata(document,self.issuer)
            self.closed=True;self.timer.stop();self.finished.emit({'resource':self.resource,'authorization_server':metadata})
        except (ValueError,TypeError,UnicodeError,RecursionError):self.stop('OAuth metadata was invalid or did not match the server.')

    def stop(self,message='OAuth discovery cancelled.'):
        if self.closed:return
        self.closed=True;self.timer.stop();reply=self.reply;self.reply=None
        if reply:reply.abort();reply.deleteLater()
        self.finished.emit({'error':message})

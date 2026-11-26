"""Asynchronous, bounded discovery for remote MCP authorization metadata."""
import json
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
from . import tls
from .mcp_oauth import _object_pairs,protected_resource_metadata_urls,authorization_server_metadata_urls

from .mcp_oauth_metadata import MAX_METADATA,parse_resource_metadata,parse_authorization_metadata


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

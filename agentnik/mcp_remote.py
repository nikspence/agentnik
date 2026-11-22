"""Bounded, asynchronous HTTP MCP discovery and explicitly reviewed calls."""
import json
import copy
import math
import time
import uuid
from collections import deque
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply
from .mcp_support import response_limit,PROTOCOL,initialize_request,parse_initialize,rpc_error,server_timeout,progress_notice,created_task_id,validate_task_result,invalidate_server_list,MCPListChangedError,task_status_notice,server_log_notice
from .mcp_resources import ResourcePages,TemplatePages,expand_template,parse_resource_contents,tool_resource_links,merge_resource_links
from .mcp_prompts import PromptPages,parse_prompt_messages,validate_prompt_arguments
from . import tls
from .mcp_2026 import PROTOCOL as MODERN_PROTOCOL,prepare_request,header_fields,parse_discovery,INPUT_REQUIRED_ERROR

HTTP_PROTOCOLS=(PROTOCOL,'2025-06-18','2025-03-26')
MAX_PAGES=5
MAX_TOOLS=100
MAX_DESCRIPTION=8000
MAX_SCHEMA=32000
MAX_DETAILS=200000

def preview_tool(item):
    """Keep bounded server-provided metadata for display, never execution."""
    description=item.get('description','');schema=item.get('inputSchema')
    execution=item.get('execution',{})
    if not isinstance(execution,dict):raise ValueError('Invalid MCP tool execution metadata')
    task_support=execution.get('taskSupport','forbidden')
    if task_support not in ('forbidden','optional','required'):raise ValueError('Unsupported MCP task execution metadata')
    if not isinstance(description,str):raise ValueError('Invalid MCP tool description')
    if schema is not None and not isinstance(schema,dict):raise ValueError('Invalid MCP input schema')
    description_bytes=description.encode('utf-8');description_clipped=len(description_bytes)>MAX_DESCRIPTION
    description=description_bytes[:MAX_DESCRIPTION].decode('utf-8','ignore')
    detail={'description':description,'description_clipped':description_clipped,'task_support':task_support}
    if 'annotations' in item:
        annotations=item['annotations']
        if not isinstance(annotations,dict):raise ValueError('Invalid MCP tool annotations')
        hints={}
        for key in ('title','readOnlyHint','destructiveHint','idempotentHint','openWorldHint'):
            if key not in annotations:continue
            value=annotations[key]
            if key=='title':
                if not isinstance(value,str) or len(value)>256 or any(ord(ch)<32 or ord(ch)==127 for ch in value):raise ValueError('Invalid MCP tool annotation')
            elif type(value) is not bool:raise ValueError('Invalid MCP tool annotation')
            hints[key]=value
        detail['annotations']=hints
    if 'outputSchema' in item:
        output=item['outputSchema']
        if not isinstance(output,dict):raise ValueError('Invalid MCP output schema')
        encoded_output=json.dumps(output,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')
        detail['output_schema']=output if len(encoded_output)<=MAX_SCHEMA else None
        detail['output_schema_status']='available' if len(encoded_output)<=MAX_SCHEMA else 'oversized'
    if schema is None:return dict(detail,schema=None,schema_status='missing')
    encoded=json.dumps(schema,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')
    if len(encoded)>MAX_SCHEMA:return dict(detail,schema=None,schema_status='oversized')
    return dict(detail,schema=schema,schema_status='available')


def contains_secret(value,secret):
    if isinstance(value,str):return secret in value
    if isinstance(value,list):return any(contains_secret(item,secret) for item in value)
    if isinstance(value,dict):return any(contains_secret(key,secret) or contains_secret(item,secret) for key,item in value.items())
    return False


def response_message(data,content_type,expected_id,on_list_changed=None,on_server_request=None):
    if content_type=='application/json':messages=[data]
    elif content_type=='text/event-stream':
        messages=[];parts=[]
        if data.startswith(b'\xef\xbb\xbf'):data=data[3:]
        # Normalize the three SSE line terminators; a blank line dispatches an event.
        lines=data.replace(b'\r\n',b'\n').replace(b'\r',b'\n').split(b'\n')
        for line in lines[:-1]:
            if not line:
                if parts and any(parts):messages.append(b'\n'.join(parts))
                parts=[];continue
            if line.startswith(b':'):continue
            field,separator,value=line.partition(b':')
            if field==b'data':
                if separator and value.startswith(b' '):value=value[1:]
                parts.append(value)
        # Never accept an unterminated data event, even after a valid response.
        if parts or lines[-1].partition(b':')[0]==b'data':raise ValueError('Incomplete MCP event stream')
    else:raise ValueError('Unsupported MCP response type')
    found=[]
    for raw in messages:
        try:message=json.loads(raw)
        except (ValueError,UnicodeError,RecursionError):raise ValueError('Invalid MCP response') from None
        if not isinstance(message,dict) or message.get('jsonrpc')!='2.0':raise ValueError('Invalid MCP response')
        if 'id' in message and 'method' in message:
            if on_server_request is None:raise ValueError('Unsupported server request or unexpected response')
            on_server_request(message)
        elif message.get('id')==expected_id and type(message.get('id')) is int:found.append(message)
        elif 'id' in message:raise ValueError('Unsupported server request or unexpected response')
        elif message.get('method') in ('notifications/tools/list_changed','notifications/resources/list_changed','notifications/prompts/list_changed'):
            if on_list_changed is None:raise MCPListChangedError('MCP server list changed')
            on_list_changed(message['method'])
    if len(found)!=1:raise ValueError('Missing or duplicate MCP response')
    return found[0]


class RemoteProbe(QObject):
    finished=Signal(object)
    progress=Signal(object)
    elicitation_requested=Signal(object)
    def __init__(self,url,token,parent=None,invocation=None,expected_identity=None,timeout_seconds=60):
        super().__init__(parent);self.url=url;self.token=token;self.invocation=invocation;self.expected_identity=expected_identity;self.manager=QNetworkAccessManager(self);self.reply=None;self.buffer=bytearray();self.session='';self.protocol=PROTOCOL;self.phase='initialize';self.result=None;self.pages=0;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set();self.next_id=0;self.current_id=None
        self.timeout_ms=1000*server_timeout({'timeout_seconds':timeout_seconds});self.failure=None;self.oauth_challenge=None;self.modern=False;self.call_schema=None;self.legacy_rejection=None;self.elicitation_enabled=False;self.elicitation_original=None;self.elicitation_pending=None
        self.progress_token=None;self.progress_last=None;self.progress_count=0;self.progress_emitted_at=0;self.progress_final_seen=False
        self.task_mode=False;self.task_id=None;self.task_cancelled=None;self.task_status_last=None;self.task_status_count=0;self.log_count=0
        self.sse_pos=0;self.sse_search=0;self.sse_parts=[];self.sse_first_line=True
        self.sse_event_end=0;self.sse_event_id=None;self.sse_last_id=b'';self.sse_retry_ms=1000;self.sse_resuming=False
        self.sse_resume_timer=QTimer(self);self.sse_resume_timer.setSingleShot(True);self.sse_resume_timer.timeout.connect(self.resume_response_stream)
        self.server_pings={};self.server_ping_error=None;self.server_ping_replies=set()
        self.server_stream=None;self.server_stream_buffer=bytearray();self.server_stream_parts=[];self.server_stream_bytes=0;self.server_stream_first=True;self.server_stream_requests=deque();self.server_stream_pending=set()
        self.server_stream_enabled=False;self.server_stream_last_id=b'';self.server_stream_event_id=None;self.server_stream_seen=deque(maxlen=128);self.server_stream_retry_ms=1000;self.server_stream_retry_deadline=0;self.server_stream_notified=False
        self.server_stream_timer=QTimer(self);self.server_stream_timer.setSingleShot(True);self.server_stream_timer.timeout.connect(self.resume_server_stream)
        self.subscription_id=None;self.subscription_ack=None
        self.subscription_timer=QTimer(self);self.subscription_timer.setSingleShot(True);self.subscription_timer.timeout.connect(self.subscription_timed_out)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.stop('MCP connection timed out.'))
    def start(self):
        self.timer.start(self.timeout_ms);self.send(initialize_request(elicitation=self.elicitation_enabled))
    def send(self,message):
        if self.modern and message.get('method') in ('tools/call','prompts/get','resources/read') and 'inputResponses' not in message.get('params',{}):self.elicitation_original=copy.deepcopy(message)
        if 'id' in message:
            self.next_id+=1;self.current_id=self.next_id;message=dict(message,id=self.current_id)
        if self.phase!='task_result':self.progress_token=None;self.progress_last=None;self.progress_count=0;self.progress_emitted_at=0
        self.progress_final_seen=False
        self.sse_pos=0;self.sse_search=0;self.sse_parts=[];self.sse_first_line=True
        self.sse_resume_timer.stop();self.sse_event_end=0;self.sse_event_id=None;self.sse_last_id=b'';self.sse_retry_ms=1000;self.sse_resuming=False
        self.server_pings={};self.server_ping_error=None
        if self.phase=='call' and message.get('method')=='tools/call':
            self.log_count=0;self.progress_token=uuid.uuid4().hex;message=dict(message);message['params']=dict(message['params'],_meta={'progressToken':self.progress_token})
        modern_headers={}
        if self.modern:message,modern_headers=prepare_request(message,self.call_schema if message.get('method')=='tools/call' else None,{'elicitation':{'form':{},'url':{}}} if self.elicitation_enabled else None)
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        tls.configure_qt_request(request)
        request.setRawHeader(b'Content-Type',b'application/json');request.setRawHeader(b'Accept',b'application/json, text/event-stream')
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        if self.modern:
            for name,value in modern_headers.items():request.setRawHeader(name.encode('ascii'),value.encode('ascii'))
        elif self.phase!='initialize':
            request.setRawHeader(b'MCP-Protocol-Version',self.protocol.encode())
            if self.session:request.setRawHeader(b'Mcp-Session-Id',self.session.encode('ascii'))
        self.buffer=bytearray();self.reply=self.manager.post(request,json.dumps(message).encode());self.configure_reply();self.reply.readyRead.connect(self.consume);self.reply.finished.connect(self.received)

    def continue_elicitation(self,responses):
        if getattr(self,'closed',False) or self.elicitation_pending is None:return False
        legacy=self.elicitation_pending.get('legacy_request')
        if legacy is None and (self.elicitation_original is None or self.reply is not None):return False
        try:
            from .mcp_elicitation import continuation
            message=continuation(self.elicitation_original if legacy is None else {'params':{}},self.elicitation_pending,responses)
            if self.token and contains_secret(responses,self.token):raise ValueError()
        except (ValueError,TypeError,UnicodeError,RecursionError):self.stop('Invalid MCP input response; the request was not continued.');return False
        self.elicitation_pending=None;self.timer.start(self.timeout_ms)
        if legacy is not None:
            ident,standalone=legacy;key=(type(ident).__name__,ident)
            try:self.post_server_response(ident,{'result':responses['request']},key,standalone)
            except (ValueError,TypeError,UnicodeError,RecursionError):self.stop('Unable to send MCP input response.');return False
            return True
        self.send(message);return self.reply is not None
    def configure_reply(self):
        if tls.relaxed(): self.reply.sslErrors.connect(lambda _errors,reply=self.reply:reply.ignoreSslErrors())
    def consume(self,final=False):
        if not self.reply:return
        self.buffer.extend(bytes(self.reply.readAll()))
        if len(self.buffer)>response_limit(self.phase):self.stop('MCP response exceeded the output limit.');return
        ctype=str(self.reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower()
        status=self.reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if self.phase not in ('initialized','closing','task_cancel','request_cancel') and status==200 and ctype=='text/event-stream':
            self.consume_progress(final)
            if self.server_ping_error:self.stop(self.server_ping_error)
            elif not final and self.progress_final_seen:self.received()

    def consume_progress(self,final=False):
        """Inspect completed SSE events while retaining the full response for validation."""
        data=self.buffer;length=len(data)
        while self.sse_search<length:
            cr=data.find(b'\r',self.sse_search);lf=data.find(b'\n',self.sse_search)
            ends=[index for index in (cr,lf) if index>=0]
            if not ends:self.sse_search=length;break
            end=min(ends)
            if data[end]==13 and end+1==length and not final:self.sse_search=end;break
            line=bytes(data[self.sse_pos:end]);step=2 if data[end]==13 and end+1<length and data[end+1]==10 else 1
            self.sse_pos=end+step;self.sse_search=self.sse_pos
            if self.sse_first_line:
                self.sse_first_line=False
                if line.startswith(b'\xef\xbb\xbf'):line=line[3:]
            if not line:
                self.sse_event_end=self.sse_pos
                if self.sse_event_id is not None:self.sse_last_id=self.sse_event_id
                self.sse_event_id=None
                if self.sse_parts and any(self.sse_parts):self._progress_event(b'\n'.join(self.sse_parts))
                self.sse_parts=[];continue
            if line.startswith(b':'):continue
            field,separator,value=line.partition(b':')
            if field==b'data':
                if separator and value.startswith(b' '):value=value[1:]
                self.sse_parts.append(value)
            elif field==b'id' and not self.modern:
                if separator and value.startswith(b' '):value=value[1:]
                try:
                    value.decode('utf-8')
                    if len(value)<=1024 and not any(ch<32 or ch==127 for ch in value) and not (self.token and self.token.encode('ascii') in value):self.sse_event_id=value
                except UnicodeError:pass
            elif field==b'retry' and not self.modern:
                if separator and value.startswith(b' '):value=value[1:]
                if value.isdigit():self.sse_retry_ms=max(1000,int(value)) if len(value)<=9 else None

    def resume_response_stream(self):
        if not self.sse_resuming or self.reply is not None:return
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy);tls.configure_qt_request(request)
        request.setRawHeader(b'Accept',b'text/event-stream');request.setRawHeader(b'Last-Event-ID',self.sse_last_id);request.setRawHeader(b'MCP-Protocol-Version',self.protocol.encode())
        if self.session:request.setRawHeader(b'Mcp-Session-Id',self.session.encode('ascii'))
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        self.reply=self.manager.get(request);self.configure_reply();self.reply.readyRead.connect(self.consume);self.reply.finished.connect(self.received)

    def _progress_event(self,data):
        if self.server_ping_error:return
        try:message=json.loads(data)
        except (ValueError,UnicodeError,RecursionError):return
        if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or (self.token and contains_secret(message,self.token)):return
        if 'id' in message and 'method' in message:
            if self.modern:self.server_ping_error='Unexpected server request in MCP 2026 response.';return
            if self.phase=='initialize' and message.get('method')!='ping':self.server_ping_error='Unexpected MCP server request during initialization.';return
            if self.progress_final_seen:self.server_ping_error='Unexpected MCP server request after the response.';return
            try:self.server_request(message)
            except ValueError:self.server_ping_error='Invalid or unsupported MCP server request.'
            return
        if type(message.get('id')) is int and message['id']==self.current_id:
            if self.elicitation_pending is not None:self.server_ping_error='MCP operation completed while user input was pending.';return
            self.progress_final_seen=True;return
        if self.progress_final_seen:return
        if self.log_count<20:
            detail=server_log_notice(message)
            if detail:self.log_count+=1;self.progress.emit(detail)
        if self.phase=='task_result' and self.task_status_count<40:
            status=task_status_notice(message,self.task_id,self.task_status_last)
            if status:self.task_status_last,detail=status;self.task_status_count+=1;self.progress.emit(detail)
        notice=progress_notice(message,self.progress_token,self.progress_last)
        if notice:
            self.progress_last,detail=notice;now=time.monotonic()
            if self.progress_count<40 and now-self.progress_emitted_at>=.25:
                self.progress_count+=1;self.progress_emitted_at=now;self.progress.emit(detail)

    def server_request(self,message,standalone=False):
        ident=message.get('id');params=message.get('params');method=message.get('method')
        if not isinstance(method,str) or not method or len(method)>256 or (type(ident) is not int and (not isinstance(ident,str) or len(ident)>128)) or (params is not None and not isinstance(params,dict)) or 'result' in message or 'error' in message:raise ValueError('Invalid server request')
        key=(type(ident).__name__,ident)
        now=time.monotonic()
        if standalone:
            while self.server_stream_requests and self.server_stream_requests[0]<=now-10:self.server_stream_requests.popleft()
            if key in self.server_stream_pending or len(self.server_stream_requests)>=32:raise ValueError('Excessive server requests')
            self.server_stream_requests.append(now);self.server_stream_pending.add(key)
        else:
            if key in self.server_pings or len(self.server_pings)>=32:raise ValueError('Excessive server requests')
            self.server_pings[key]=message
        if method=='elicitation/create' and self.elicitation_enabled and self.protocol in ('2025-06-18','2025-11-25') and self.phase in ('call','resource_read','prompt_get') and self.elicitation_pending is None:
            from .mcp_elicitation import parse_legacy_request
            try:
                self.elicitation_pending=parse_legacy_request(params,self.protocol);self.elicitation_pending['legacy_request']=(ident,standalone)
            except (ValueError,TypeError,RecursionError):
                self.post_server_response(ident,{'error':{'code':-32602,'message':'Unsupported elicitation request'}},key,standalone);return
            self.timer.stop();self.elicitation_requested.emit(self.elicitation_pending['forms']);return
        response={'result':{}} if method=='ping' else {'error':{'code':-32601,'message':'Method not supported'}}
        self.post_server_response(ident,response,key,standalone)

    def post_server_response(self,ident,response,key,standalone):
        if len(self.server_ping_replies)>=4:raise ValueError('Excessive server requests')
        is_elicitation=isinstance(response.get('result'),dict) and response['result'].get('action') in ('accept','decline','cancel')
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy);tls.configure_qt_request(request)
        request.setRawHeader(b'Content-Type',b'application/json');request.setRawHeader(b'Accept',b'application/json, text/event-stream')
        request.setRawHeader(b'MCP-Protocol-Version',self.protocol.encode())
        session=self.session
        if self.phase=='initialize' and self.reply:
            raw_session=self.reply.rawHeader('Mcp-Session-Id')
            try:session=raw_session if isinstance(raw_session,str) else bytes(raw_session).decode('ascii')
            except UnicodeError:raise ValueError('Invalid MCP session identifier') from None
            if len(session)>512 or any(ord(ch)<33 or ord(ch)>126 for ch in session):raise ValueError('Invalid MCP session identifier')
            if self.sse_resuming:
                if session and self.session and session!=self.session:raise ValueError('MCP session identifier changed')
                session=session or self.session
        if session:request.setRawHeader(b'Mcp-Session-Id',session.encode('ascii'))
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        response=dict(response,jsonrpc='2.0',id=ident)
        origin=self.reply;reply=self.manager.post(request,json.dumps(response).encode());self.server_ping_replies.add(reply)
        reply.setReadBufferSize(1024)
        ping_timer=QTimer(reply);ping_timer.setSingleShot(True);ping_timer.timeout.connect(reply.abort);ping_timer.start(min(self.timeout_ms,3000))
        if tls.relaxed():reply.sslErrors.connect(lambda _errors,reply=reply:reply.ignoreSslErrors())
        def finished():
            status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute);invalid=status!=202 or reply.bytesAvailable()!=0
            self.server_ping_replies.discard(reply);self.server_stream_pending.discard(key);reply.deleteLater()
            if invalid and is_elicitation and self.phase not in ('closing','task_cancel','request_cancel'):self.stop('MCP server did not accept the input response.')
            elif invalid and standalone:self.close_server_stream()
            elif invalid and self.reply is origin and self.phase not in ('closing','task_cancel','request_cancel'):self.stop('MCP server did not accept a client response.')
        reply.finished.connect(finished)

    def verify_server_ping(self,message):
        ident=message.get('id');key=(type(ident).__name__,ident) if type(ident) is int or isinstance(ident,str) else None
        if key not in self.server_pings or self.server_pings[key]!=message:raise ValueError('Unsupported server request')

    def open_server_stream(self):
        """Open the optional, independent server-to-client event stream."""
        if self.server_stream is not None:return
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy);tls.configure_qt_request(request)
        request.setRawHeader(b'Accept',b'application/json, text/event-stream' if self.modern else b'text/event-stream');request.setRawHeader(b'MCP-Protocol-Version',self.protocol.encode())
        if not self.modern and self.server_stream_last_id:request.setRawHeader(b'Last-Event-ID',self.server_stream_last_id)
        if not self.modern and self.session:request.setRawHeader(b'Mcp-Session-Id',self.session.encode('ascii'))
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        if self.modern:
            self.next_id+=1;self.subscription_id=self.next_id;self.subscription_ack=None
            message,headers=prepare_request({'jsonrpc':'2.0','id':self.subscription_id,'method':'subscriptions/listen','params':{'notifications':self.result['subscription_filters']}})
            for name,value in headers.items():request.setRawHeader(name.encode('ascii'),value.encode('ascii'))
            request.setRawHeader(b'Content-Type',b'application/json');reply=self.manager.post(request,json.dumps(message).encode());self.subscription_timer.start(self.timeout_ms)
        else:reply=self.manager.get(request)
        self.server_stream=reply;self.server_stream_buffer=bytearray();self.server_stream_parts=[];self.server_stream_bytes=0;self.server_stream_first=True;self.server_stream_event_id=None
        reply.setReadBufferSize(65536)
        if tls.relaxed():reply.sslErrors.connect(lambda _errors,reply=reply:reply.ignoreSslErrors())
        reply.readyRead.connect(lambda:self.read_server_stream(reply));reply.finished.connect(lambda:self.finish_server_stream(reply))

    def close_server_stream(self):
        self.server_stream_enabled=False;self.server_stream_timer.stop();self.subscription_timer.stop()
        reply=self.server_stream;self.server_stream=None
        if reply:
            reply.abort();reply.deleteLater()
        self.server_stream_buffer.clear();self.server_stream_parts=[];self.server_stream_bytes=0

    def subscription_timed_out(self):
        if self.modern and self.server_stream and self.subscription_ack is None:
            self.subscription_failed('MCP change notification subscription was not acknowledged; list resources and prompts again.')

    def subscription_failed(self,message):
        self.close_server_stream();self.resource_items=[];self.template_items=[];self.prompt_items=[];self.subscription_ack=None
        self.progress.emit(message)

    def finish_server_stream(self,reply):
        if self.server_stream is not reply:return
        self.read_server_stream(reply,final=True)
        if self.server_stream is not reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error=reply.error();self.server_stream=None;reply.deleteLater();self.subscription_timer.stop()
        if not self.server_stream_enabled:return
        if status in (204,400,401,403,404,405,410,501) or error==QNetworkReply.NetworkError.SslHandshakeFailedError:
            if self.modern:self.subscription_failed('MCP change notification subscription ended; list resources and prompts again.')
            else:self.server_stream_enabled=False
            return
        self.server_stream_buffer.clear();self.server_stream_parts=[];self.server_stream_bytes=0;self.server_stream_event_id=None
        self.resource_items=[];self.template_items=[];self.prompt_items=[]
        if not self.server_stream_notified:
            self.server_stream_notified=True;self.progress.emit('MCP server event stream disconnected; list resources and prompts again.'+(' Reconnecting.' if self.server_stream_retry_ms is not None else ' Server retry delay is too large to schedule.'))
        if not self.server_stream_enabled:return
        if self.server_stream_retry_ms is None:return
        self.server_stream_retry_deadline=time.monotonic()+self.server_stream_retry_ms/1000
        self.resume_server_stream()

    def resume_server_stream(self):
        if not self.server_stream_enabled or self.server_stream is not None:return
        remaining=self.server_stream_retry_deadline-time.monotonic()
        if remaining>0:self.server_stream_timer.start(min(2147483000,max(1,math.ceil(remaining*1000))));return
        self.open_server_stream()

    def read_server_stream(self,reply,final=False):
        if self.server_stream is not reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        content_type=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower()
        if status!=200 or content_type!='text/event-stream':
            if status==200 or status in (204,400,401,403,404,405,410,501):
                if self.modern:self.subscription_failed('MCP change notification subscription was unavailable; list resources and prompts again.')
                else:self.close_server_stream()
            return
        self.server_stream_buffer.extend(bytes(reply.readAll()))
        if len(self.server_stream_buffer)+self.server_stream_bytes>65536:self.close_server_stream();return
        while self.server_stream is reply:
            data=self.server_stream_buffer;cr=data.find(b'\r');lf=data.find(b'\n');ends=[i for i in (cr,lf) if i>=0]
            if not ends:break
            end=min(ends)
            if data[end]==13 and end+1==len(data) and not final:break
            line=bytes(data[:end]);step=2 if data[end]==13 and end+1<len(data) and data[end+1]==10 else 1;del data[:end+step]
            if self.server_stream_first:
                self.server_stream_first=False
                if line.startswith(b'\xef\xbb\xbf'):line=line[3:]
            if not line:
                event_id=self.server_stream_event_id
                duplicate=bool(event_id and event_id in self.server_stream_seen)
                if event_id is not None:
                    self.server_stream_last_id=event_id
                    if event_id and not duplicate:self.server_stream_seen.append(event_id)
                if self.server_stream_parts and any(self.server_stream_parts):
                    if not duplicate:self.server_stream_notified=False
                    self.server_stream_event(b'\n'.join(self.server_stream_parts),duplicate=duplicate)
                self.server_stream_parts=[];self.server_stream_bytes=0;self.server_stream_event_id=None;continue
            if line.startswith(b':'):continue
            field,separator,value=line.partition(b':')
            if field==b'data':
                if separator and value.startswith(b' '):value=value[1:]
                self.server_stream_parts.append(value);self.server_stream_bytes+=len(value)+1
                if self.server_stream_bytes>65536:self.close_server_stream();return
            elif field==b'id' and not self.modern:
                if separator and value.startswith(b' '):value=value[1:]
                try:
                    value.decode('utf-8')
                    if len(value)<=1024 and not any(ch<32 or ch==127 for ch in value) and not (self.token and self.token.encode('ascii') in value):self.server_stream_event_id=value
                except UnicodeError:pass
            elif field==b'retry' and not self.modern:
                if separator and value.startswith(b' '):value=value[1:]
                if value.isdigit():self.server_stream_retry_ms=max(1000,int(value)) if len(value)<=128 else None

    def server_stream_event(self,data,duplicate=False):
        try:
            message=json.loads(data)
            if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or (self.token and contains_secret(message,self.token)):raise ValueError()
            if self.modern:
                if 'id' in message:
                    if message.get('id')!=self.subscription_id or 'method' in message:raise ValueError()
                    return
                params=message.get('params');meta=params.get('_meta') if isinstance(params,dict) else None
                if not isinstance(meta,dict) or type(meta.get('io.modelcontextprotocol/subscriptionId')) is not int or meta['io.modelcontextprotocol/subscriptionId']!=self.subscription_id:raise ValueError()
                method=message.get('method')
                if self.subscription_ack is None:
                    selected=params.get('notifications');requested=self.result['subscription_filters']
                    if method!='notifications/subscriptions/acknowledged' or not isinstance(selected,dict) or any(key not in requested or type(value) is not bool or value and not requested[key] for key,value in selected.items()):raise ValueError()
                    self.subscription_ack={key for key,value in selected.items() if value};self.subscription_timer.stop()
                    missing=set(requested)-self.subscription_ack
                    if missing:
                        if 'resourcesListChanged' in missing:self.resource_items=[];self.template_items=[]
                        if 'promptsListChanged' in missing:self.prompt_items=[]
                        self.progress.emit('MCP server declined some change notifications; relist resources and prompts before using them.')
                    return
                mapping={'notifications/tools/list_changed':'toolsListChanged','notifications/resources/list_changed':'resourcesListChanged','notifications/prompts/list_changed':'promptsListChanged'}
                if method not in mapping or mapping[method] not in self.subscription_ack:raise ValueError()
                self.list_changed(method);return
            if 'id' in message:
                if 'method' not in message:raise ValueError()
                ident=message['id'];key=(type(ident).__name__,ident) if type(ident) is int or isinstance(ident,str) else None
                if duplicate and (key in self.server_stream_pending or message.get('method')=='elicitation/create'):return
                self.server_request(message,standalone=True);return
            if duplicate:return
            if message.get('method') in ('notifications/tools/list_changed','notifications/resources/list_changed','notifications/prompts/list_changed'):
                self.list_changed(message['method']);return
            if self.phase in ('call','task_result'):
                detail=server_log_notice(message)
                if detail and self.log_count<20:self.log_count+=1;self.progress.emit(detail)
                if self.phase=='task_result' and self.task_status_count<40:
                    status=task_status_notice(message,self.task_id,self.task_status_last)
                    if status:self.task_status_last,detail=status;self.task_status_count+=1;self.progress.emit(detail)
                notice=progress_notice(message,self.progress_token,self.progress_last)
                if notice:
                    self.progress_last,detail=notice;now=time.monotonic()
                    if self.progress_count<40 and now-self.progress_emitted_at>=.25:self.progress_count+=1;self.progress_emitted_at=now;self.progress.emit(detail)
        except MCPListChangedError as exc:self.stop(str(exc))
        except (ValueError,UnicodeError,TypeError,RecursionError):
            if self.modern:self.subscription_failed('MCP change notification subscription returned an invalid message; list resources and prompts again.')
            else:self.close_server_stream()

    def list_changed(self,method):
        notice=invalidate_server_list(self,method)
        if notice:self.progress.emit(notice)
    def received(self):
        reply=self.reply
        if reply is None:return
        self.consume(final=True)
        if self.reply is not reply:return
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower()
        resumable_stream=status==200 and ctype=='text/event-stream'
        transient_resume=self.sse_resuming and (status is None or isinstance(status,int) and 500<=status<600) and reply.error()!=QNetworkReply.NetworkError.SslHandshakeFailedError
        if not self.modern and self.phase not in ('initialized','closing','task_cancel','request_cancel') and (resumable_stream or transient_resume) and not self.progress_final_seen and self.sse_last_id and self.sse_retry_ms is not None:
            if self.phase=='initialize' and not self.sse_resuming:
                try:
                    session=reply.rawHeader('Mcp-Session-Id')
                    if not isinstance(session,str):session=bytes(session).decode('ascii')
                    if len(session)>512 or any(ord(ch)<33 or ord(ch)>126 for ch in session):raise ValueError()
                    self.session=session
                except (ValueError,UnicodeError,TypeError):self.stop('Invalid MCP session identifier.');return
            self.reply=None;reply.deleteLater();del self.buffer[self.sse_event_end:]
            self.sse_pos=self.sse_event_end;self.sse_search=self.sse_event_end;self.sse_parts=[];self.sse_event_id=None;self.sse_first_line=False;self.sse_resuming=True
            self.progress.emit('MCP response stream disconnected; resuming without repeating the request.')
            if self.sse_resuming:self.sse_resume_timer.start(self.sse_retry_ms)
            return
        stream_finished=resumable_stream and self.progress_final_seen
        was_resuming=self.sse_resuming;self.sse_resuming=False
        self.reply=None
        if stream_finished:
            reply.finished.disconnect(self.received);reply.readyRead.disconnect(self.consume);reply.abort()
        reply.deleteLater()
        if self.phase=='closing':
            self.complete(isinstance(status,int) and 200<=status<300);return
        if self.phase=='request_cancel':
            self.close_session();return
        if self.phase=='task_cancel':
            self.task_cancelled=False
            try:
                if status!=200:raise ValueError('Task cancellation failed')
                ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower()
                message=response_message(bytes(self.buffer),ctype,self.current_id)
                if self.token and contains_secret(message,self.token):raise ValueError('Credential reflected in response')
                task=message.get('result')
                self.task_cancelled=isinstance(task,dict) and task.get('taskId')==self.task_id and task.get('status')=='cancelled'
            except (ValueError,UnicodeError,TypeError,RecursionError):pass
            self.close_session();return
        if status not in ((202,) if self.phase=='initialized' else (200,)):
            if self.phase=='initialize' and status in (400,404,405):
                self.legacy_rejection='HTTP '+str(status);self.modern=True;self.protocol=MODERN_PROTOCOL;self.phase='modern_discovery'
                self.progress.emit('Legacy MCP initialization was rejected; checking 2026 discovery.')
                self.send({'jsonrpc':'2.0','id':0,'method':'server/discover','params':{}});return
            if status in (401,403):
                from .mcp_oauth import bearer_challenge
                header=reply.rawHeader('WWW-Authenticate')
                challenge=bearer_challenge(header if isinstance(header,str) else bytes(header).decode('latin-1'))
                if challenge is not None:
                    if not self.token or not contains_secret(challenge,self.token):self.oauth_challenge={key:challenge[key] for key in ('resource_metadata','scope') if key in challenge}
                    if status==403 and challenge.get('error')=='insufficient_scope':self.stop('MCP authorization has insufficient scope. Sign in again or use a bearer token with the required permissions.');return
                    if status==401:self.stop('MCP server requires a valid bearer token. Sign in or enter one in MCP server settings.');return
            if self.phase=='modern_discovery' and self.legacy_rejection is not None and isinstance(status,int):
                self.stop('MCP server rejected legacy initialization ('+self.legacy_rejection+') and 2026 discovery (HTTP '+str(status)+').');return
            self.stop('MCP server returned an HTTP or network error'+(' ('+str(status)+').' if isinstance(status,int) else '.'));return
        try:
            if self.token and self.token.encode('ascii') in self.buffer:raise ValueError('Credential reflected in response')
            if self.phase=='initialized':
                self.server_stream_enabled=True
                self.open_server_stream()
                if 'tools' not in self.result['capabilities']:
                    if self.invocation:raise ValueError('MCP tools unavailable')
                    self.result['tools']=[];self.result['tool_details']=[];self.result['more_tools']=False;self.finish_discovery();return
                self.phase='tools';self.pages=1;self.send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}});return
            ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower()
            message=response_message(bytes(self.buffer),ctype,self.current_id,self.list_changed,None if self.modern else self.verify_server_ping)
            if not self.modern and self.elicitation_pending is not None:raise ValueError('MCP operation completed while user input was pending')
            if self.token and contains_secret(message,self.token):raise ValueError('Credential reflected in response')
            if 'error' in message:
                if self.phase=='initialize' and isinstance(message['error'],dict) and message['error'].get('code') in (-32601,-32022):
                    self.legacy_rejection='JSON-RPC '+str(message['error']['code']);self.modern=True;self.protocol=MODERN_PROTOCOL;self.phase='modern_discovery'
                    self.progress.emit('Legacy MCP initialization was rejected; checking 2026 discovery.')
                    self.send({'jsonrpc':'2.0','id':0,'method':'server/discover','params':{}});return
                error=rpc_error(message)
                if self.phase=='completion':self.timer.stop();self.phase='ready';self.called.emit({'error':error});return
                self.stop(error);return
            if self.modern and self.phase in ('call','resource_read','prompt_get') and isinstance(message.get('result'),dict) and message['result'].get('resultType')=='input_required':
                if not self.elicitation_enabled or self.elicitation_original is None:self.stop(INPUT_REQUIRED_ERROR);return
                try:
                    from .mcp_elicitation import parse_input_required
                    self.elicitation_pending=parse_input_required(message['result'])
                except (ValueError,TypeError,UnicodeError,RecursionError):self.stop(INPUT_REQUIRED_ERROR);return
                self.timer.stop();self.elicitation_requested.emit(self.elicitation_pending['forms']);return
            if self.modern and self.phase in ('call','resource_read','prompt_get'):self.elicitation_original=None;self.elicitation_pending=None
            if self.phase=='modern_discovery':
                self.result=parse_discovery(message.get('result'))
                if self.expected_identity and any(self.result.get(key)!=value for key,value in self.expected_identity.items()):raise ValueError('MCP server identity changed')
                if self.result['subscription_filters']:
                    self.server_stream_enabled=True;self.open_server_stream()
                if 'tools' not in self.result['capabilities']:
                    if self.invocation:raise ValueError('MCP tools unavailable')
                    self.result.update(tools=[],tool_details=[],more_tools=False);self.finish_discovery();return
                self.phase='tools';self.pages=1;self.send({'jsonrpc':'2.0','id':0,'method':'tools/list','params':{}});return
            if self.phase=='initialize':
                self.result=parse_initialize(json.dumps(message).encode(),HTTP_PROTOCOLS);self.protocol=self.result['protocol']
                session=reply.rawHeader('Mcp-Session-Id')
                if not isinstance(session,str):session=bytes(session).decode('ascii')
                if len(session)>512 or any(ord(ch)<33 or ord(ch)>126 for ch in session):raise ValueError('Invalid MCP session identifier')
                if was_resuming and session and self.session and session!=self.session:raise ValueError('MCP session identifier changed')
                if session or not was_resuming:self.session=session
                if self.expected_identity and any(self.result.get(key)!=value for key,value in self.expected_identity.items()):raise ValueError('MCP server identity changed')
                self.phase='initialized';self.send({'jsonrpc':'2.0','method':'notifications/initialized'});return
            if self.phase=='completion':
                from .mcp_completion import parse_completion
                outcome=parse_completion(message.get('result'))
                if self.token and contains_secret(outcome,self.token):raise ValueError('Credential reflected in response')
                self.timer.stop();self.phase='ready';self.called.emit({'completion':outcome});return
            if self.phase in ('prompt_list','prompt_get'):
                outcome=message.get('result')
                if not isinstance(outcome,dict):raise ValueError('Invalid MCP prompt response')
                if self.phase=='prompt_list':
                    cursor,outcome=self.prompt_pages.accept(outcome)
                    if cursor:self.prompt_list_page(cursor);return
                    self.prompt_items=outcome['prompts']
                    if self.prompt_invocation:
                        expected=self.prompt_invocation['prompt'];current=next((x for x in self.prompt_items if x['name']==expected['name']),None)
                        if current!=expected:self.stop('MCP prompt definition changed.');return
                        args=self.prompt_invocation['arguments'];self.prompt_invocation=None;self.phase='prompt_get'
                        self.send({'jsonrpc':'2.0','id':0,'method':'prompts/get','params':{'name':current['name'],'arguments':args}});return
                else:outcome=parse_prompt_messages(outcome)
                if self.token and contains_secret(outcome,self.token):raise ValueError('Credential reflected in response')
                self.timer.stop();self.phase='ready';self.prompts.emit(outcome);return
            if self.phase in ('resource_list','resource_read','template_list'):
                outcome=message.get('result')
                if not isinstance(outcome,dict):raise ValueError('Invalid MCP resource response')
                if self.phase=='template_list':
                    cursor,outcome=self.template_pages.accept(outcome)
                    if cursor:self.template_list_page(cursor);return
                    self.template_items=outcome['templates']
                elif self.phase=='resource_list':
                    cursor,outcome=self.resource_pages.accept(outcome)
                    if cursor:self.resource_list_page(cursor);return
                    self.resource_items=outcome['resources']
                else:outcome=parse_resource_contents(outcome,self.resource_uri)
                if self.token and contains_secret(outcome,self.token):raise ValueError('Credential reflected in response')
                self.timer.stop();self.phase='ready';self.resources.emit(outcome);return
            if self.phase=='call' and self.task_mode:
                self.task_id=created_task_id(message.get('result'));self.task_status_last='working';self.task_status_count=0;self.phase='task_result'
                self.progress.emit('Task started: '+self.task_id+'; awaiting result.')
                self.send({'jsonrpc':'2.0','id':0,'method':'tasks/result','params':{'taskId':self.task_id}});return
            if self.phase in ('call','task_result'):
                outcome=message.get('result')
                if self.modern and isinstance(outcome,dict) and outcome.get('resultType','complete')!='complete':raise ValueError('MCP multi-round-trip input is not supported')
                if self.phase=='task_result':validate_task_result(outcome,self.task_id)
                from .mcp_content import decode_tool_text_resources,normalize_tool_result
                outcome=normalize_tool_result(outcome)
                outcome=decode_tool_text_resources(outcome)
                if self.token and contains_secret(outcome,self.token):raise ValueError('Credential reflected in response')
                self.task_id=None;self.task_mode=False;self.progress_token=None
                self.result['call_result']=outcome;self.finish_call();return
            result=message.get('result');tools=result.get('tools') if isinstance(result,dict) else None
            if not isinstance(tools,list) or len(tools)>MAX_TOOLS:raise ValueError('Invalid MCP tool list')
            for item in tools:
                name=item.get('name') if isinstance(item,dict) else None
                if not isinstance(name,str) or not name or len(name)>128 or any(ord(ch)<32 or ord(ch)==127 for ch in name):raise ValueError('Invalid MCP tool name')
                if name in self.names:raise ValueError('Duplicate MCP tool name')
                self.names.append(name)
                if len(self.details)<MAX_TOOLS:
                    detail=preview_tool(item);detail['name']=name
                    if self.modern and detail['schema_status']=='available':
                        try:header_fields(detail['schema'])
                        except (ValueError,RecursionError):detail['schema_status']='invalid header annotations'
                    size=len(json.dumps(detail,ensure_ascii=True).encode('ascii'))
                    if self.detail_bytes+size>MAX_DETAILS:detail={'name':name,'description':'','description_clipped':True,'schema':None,'schema_status':'details budget exceeded'};size=len(json.dumps(detail).encode())
                    self.detail_bytes+=size;self.details.append(detail)
            cursor=result.get('nextCursor')
            if cursor is not None:
                if not isinstance(cursor,str) or not cursor or len(cursor)>1024 or cursor in self.cursors:raise ValueError('Invalid MCP cursor')
                self.cursors.add(cursor)
            if cursor and self.pages<MAX_PAGES and len(self.names)<MAX_TOOLS:
                self.pages+=1;self.send({'jsonrpc':'2.0','id':self.pages+1,'method':'tools/list','params':{'cursor':cursor}});return
            self.result['tools']=self.names[:MAX_TOOLS];self.result['tool_details']=self.details;self.result['more_tools']=bool(cursor) or len(self.names)>MAX_TOOLS
            if self.invocation:
                expected=self.invocation['tool'];current=next((item for item in self.details if item['name']==expected['name']),None)
                if current!=expected or current.get('schema_status')!='available' or not self.supports_tool(current):
                    self.stop('MCP tool definition changed; test the server again before calling.');return
                if self.invocation.get('verify_only'):
                    self.invocation=None;self.timer.stop();self.phase='ready';self.called.emit({'verified':True});return
                args=self.invocation['arguments'];payload=json.dumps(args,ensure_ascii=False,allow_nan=False)
                if not isinstance(args,dict) or len(payload.encode())>16000 or (self.token and self.token in payload):raise ValueError('Invalid MCP tool arguments')
                self.phase='call';self.task_mode=current.get('task_support')=='required';self.task_id=None
                self.call_schema=current.get('schema')
                params={'name':current['name'],'arguments':args}
                if self.task_mode:params['task']={}
                self.send({'jsonrpc':'2.0','id':self.pages+2,'method':'tools/call','params':params});return
            self.finish_discovery()
        except MCPListChangedError as exc:self.stop(str(exc))
        except (ValueError,UnicodeError,TypeError,RecursionError):self.stop('Invalid or unsupported MCP server response.')
    def finish_discovery(self):
        self.close_session()

    def supports_tool(self,tool):
        return tool.get('task_support')!='required' or bool((self.result or {}).get('task_capabilities',{}).get('tool_calls'))
    def finish_call(self):
        self.close_session()
    def close_session(self):
        self.elicitation_original=None;self.elicitation_pending=None
        self.sse_resuming=False;self.sse_resume_timer.stop()
        self.close_server_stream()
        if not self.session:self.complete(None);return
        self.phase='closing';self.timer.start(3000)
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        tls.configure_qt_request(request)
        request.setRawHeader(b'MCP-Protocol-Version',self.protocol.encode());request.setRawHeader(b'Mcp-Session-Id',self.session.encode('ascii'))
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        self.buffer=bytearray();self.reply=self.manager.deleteResource(request);self.configure_reply();self.reply.readyRead.connect(self.consume);self.reply.finished.connect(self.received)
    def complete(self,closed):
        self.timer.stop();self.token=''
        result=self.failure if self.failure is not None else self.result
        result['session_closed']=closed
        if self.task_id:result['task_id']=self.task_id
        if self.task_cancelled is not None:result['task_cancelled']=self.task_cancelled
        self.finished.emit(result)

    def cancel_task_or_close(self,request_id=None):
        if self.modern:self.close_session();return
        caps=(self.result or {}).get('task_capabilities',{})
        if self.task_id and self.phase=='task_result' and caps.get('cancel'):
            self.task_cancelled=False;self.phase='task_cancel';self.timer.start(3000)
            self.send({'jsonrpc':'2.0','id':0,'method':'tasks/cancel','params':{'taskId':self.task_id}});return
        if request_id is not None:
            self.phase='request_cancel';self.timer.start(1500)
            self.send({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':request_id}});return
        self.close_session()
    def stop(self,message='MCP connection cancelled.'):
        resuming=self.sse_resuming;self.sse_resuming=False;self.sse_resume_timer.stop()
        self.close_server_stream()
        self.timer.stop();reply=self.reply;self.reply=None
        request_id=self.current_id if (reply or resuming) and self.phase=='call' and not self.task_mode and not self.progress_final_seen else None
        if reply:
            reply.finished.disconnect(self.received);reply.readyRead.disconnect(self.consume);reply.abort();reply.deleteLater()
        if self.phase=='closing' and (self.result is not None or self.failure is not None):self.complete(False);return
        if self.phase=='task_cancel':self.task_cancelled=False;self.close_session();return
        if self.phase=='request_cancel':self.close_session();return
        if self.task_id:message+=' Task '+self.task_id+' may still be running; inspect the server before retrying.'
        self.failure={'error':message,'call_uncertain':self.phase in ('call','task_result')}
        self.cancel_task_or_close(request_id)


class RemoteSession(RemoteProbe):
    """One bounded Streamable HTTP session shared by a coding run."""
    discovered=Signal(object)
    called=Signal(object)
    ended=Signal(object)
    resources=Signal(object)
    prompts=Signal(object)

    def __init__(self,url,token,parent=None,timeout_seconds=60):
        super().__init__(url,token,parent,timeout_seconds=timeout_seconds)
        self.closed=False;self.resource_links=[]

    def finish_discovery(self):
        self.timer.stop();self.phase='ready'
        self.discovered.emit(dict(self.result,session_stateful=bool(self.session)))

    def finish_call(self):
        outcome=self.result.pop('call_result')
        self.resource_links=merge_resource_links(self.resource_links,tool_resource_links(outcome))
        self.timer.stop();self.phase='ready';self.invocation=None
        self.called.emit({'call_result':outcome})

    def verify_tool(self,tool):
        if self.closed or self.phase!='ready':return False
        self.invocation={'tool':tool,'verify_only':True}
        self.pages=1;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set()
        self.phase='tools';self.timer.start(self.timeout_ms)
        self.send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
        return True

    def call(self,tool,arguments):
        if self.closed or self.phase!='ready':return False
        self.invocation={'tool':tool,'arguments':arguments}
        self.pages=1;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set()
        self.phase='tools';self.timer.start(self.timeout_ms)
        self.send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
        return True

    def list_resources(self):
        if self.closed or self.phase!='ready' or 'resources' not in self.result['capabilities']:return False
        self.resource_items=[];self.resource_pages=ResourcePages();self.phase='resource_list';self.timer.start(self.timeout_ms)
        self.resource_list_page(None);return True

    def resource_list_page(self,cursor):
        self.send({'jsonrpc':'2.0','id':0,'method':'resources/list','params':{'cursor':cursor} if cursor else {}})

    def read_resource(self,uri):
        if self.closed or self.phase!='ready' or uri not in [item['uri'] for item in getattr(self,'resource_items',[])+self.resource_links]:return False
        if self.token and self.token in uri:return False
        self.resource_uri=uri;self.phase='resource_read';self.timer.start(self.timeout_ms)
        self.send({'jsonrpc':'2.0','id':0,'method':'resources/read','params':{'uri':uri}});return True

    def list_resource_templates(self):
        if self.closed or self.phase!='ready' or 'resources' not in self.result['capabilities']:return False
        self.template_items=[];self.template_pages=TemplatePages();self.phase='template_list';self.timer.start(self.timeout_ms)
        self.template_list_page(None);return True

    def template_list_page(self,cursor):
        self.send({'jsonrpc':'2.0','id':0,'method':'resources/templates/list','params':{'cursor':cursor} if cursor else {}})

    def read_resource_template(self,template,arguments,uri):
        if self.closed or self.phase!='ready' or template not in getattr(self,'template_items',[]) or not template['supported']:return False
        try:
            if expand_template(template['uriTemplate'],arguments)!=uri or (self.token and (contains_secret(arguments,self.token) or self.token in uri)):return False
        except (ValueError,UnicodeError):return False
        self.resource_uri=uri;self.phase='resource_read';self.timer.start(self.timeout_ms)
        self.send({'jsonrpc':'2.0','id':0,'method':'resources/read','params':{'uri':uri}});return True

    def list_prompts(self,invocation=None):
        if self.closed or self.phase!='ready' or 'prompts' not in self.result['capabilities']:return False
        if invocation:
            if invocation['prompt'] not in getattr(self,'prompt_items',[]):return False
            try:
                validate_prompt_arguments(invocation['prompt'],invocation['arguments'])
                if self.token and contains_secret(invocation['arguments'],self.token):return False
            except (ValueError,UnicodeError,RecursionError):return False
        self.prompt_invocation=invocation;self.prompt_items=[];self.prompt_pages=PromptPages();self.phase='prompt_list';self.timer.start(self.timeout_ms)
        self.prompt_list_page(None);return True

    def complete_argument(self,kind,target,argument,value,context):
        if self.closed or self.phase!='ready' or 'completions' not in self.result['capabilities']:return False
        if target not in getattr(self,'prompt_items' if kind=='prompt' else 'template_items',[]):return False
        try:
            from .mcp_completion import completion_params
            params=completion_params(kind,target,argument,value,context)
            if self.token and contains_secret(params,self.token):return False
        except (ValueError,TypeError,UnicodeError,RecursionError):return False
        self.completion_kind=kind;self.phase='completion';self.timer.start(self.timeout_ms)
        self.send({'jsonrpc':'2.0','id':0,'method':'completion/complete','params':params});return True

    def prompt_list_page(self,cursor):
        self.send({'jsonrpc':'2.0','id':0,'method':'prompts/list','params':{'cursor':cursor} if cursor else {}})

    def shutdown(self):
        if self.closed:return
        resuming=self.sse_resuming;self.sse_resuming=False;self.sse_resume_timer.stop()
        self.close_server_stream()
        self.closed=True;self.timer.stop()
        reply=self.reply;self.reply=None
        request_id=self.current_id if (reply or resuming) and self.phase=='call' and not self.task_mode and not self.progress_final_seen else None
        if reply:
            reply.finished.disconnect(self.received);reply.readyRead.disconnect(self.consume);reply.abort();reply.deleteLater()
        self.cancel_task_or_close(request_id)

    def complete(self,closed):
        self.timer.stop();self.token='';result={'session_closed':closed}
        if self.task_id:result['task_id']=self.task_id
        if self.task_cancelled is not None:result['task_cancelled']=self.task_cancelled
        self.finished.emit(result)

    def stop(self,message='MCP connection cancelled.'):
        if self.phase in ('closing','task_cancel','request_cancel'):
            super().stop(message);return
        uncertain=self.phase in ('call','task_result')
        if self.task_id:message+=' Task '+self.task_id+' may still be running; inspect the server before retrying.'
        self.ended.emit({'error':message,'call_uncertain':uncertain})
        self.shutdown()

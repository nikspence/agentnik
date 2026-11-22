"""Validate and present MCP elicitation requests."""
import json
import html
import math
import unicodedata
from urllib.parse import urlsplit
from PySide6.QtCore import Qt,QUrl,Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPlainTextEdit,QDialogButtonBox,QTabWidget,QWidget,QScrollArea,QLineEdit,QComboBox,QCheckBox)
from .mcp_schema import validate_tool_arguments,MCPArgumentValidationError


def open_elicitation_url(url):
    return QDesktopServices.openUrl(QUrl(url))


def validate_answer(schema,value):
    try:
        if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))>65536:raise ValueError('Answer is too large.')
    except (TypeError,UnicodeError,RecursionError):raise ValueError('Enter a valid JSON object.') from None
    validate_tool_arguments(schema,value)
    from jsonschema import Draft202012Validator,Draft7Validator,FormatChecker
    from jsonschema.exceptions import ValidationError
    from referencing import Registry
    dialect=schema.get('$schema','')
    validator=Draft7Validator if 'draft-07' in dialect else Draft202012Validator
    try:validator(schema,registry=Registry(),format_checker=FormatChecker()).validate(value)
    except ValidationError:raise ValueError('Answer does not match the requested format.') from None


def parse_input_required(result):
    """Extract supported elicitation requests and opaque continuation state."""
    if not isinstance(result,dict) or result.get('resultType')!='input_required':raise ValueError('Invalid MCP input request')
    try:
        if len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8'))>65536:raise ValueError('MCP input request is too large')
    except (TypeError,UnicodeError,RecursionError):raise ValueError('Invalid MCP input request') from None
    requests=result.get('inputRequests');state=result.get('requestState')
    if not isinstance(requests,dict) or not requests or len(requests)>32 or (state is not None and not isinstance(state,str)):raise ValueError('Unsupported MCP input request')
    forms=[]
    for key,request in requests.items():
        if not isinstance(key,str) or not key or len(key)>256 or not isinstance(request,dict) or request.get('method')!='elicitation/create':raise ValueError('Unsupported MCP input request')
        params=request.get('params')
        if not isinstance(params,dict) or params.get('mode','form') not in ('form','url'):raise ValueError('Unsupported MCP input request')
        message=params.get('message');mode=params.get('mode','form')
        if not isinstance(message,str) or not message or len(message)>8000:raise ValueError('Invalid MCP input request')
        if mode=='url':
            url=params.get('url')
            if not isinstance(url,str) or not url or len(url)>8192 or '\\' in url or any(ch.isspace() or unicodedata.category(ch).startswith('C') for ch in url):raise ValueError('Invalid MCP input URL')
            try:
                parts=urlsplit(url);host=parts.hostname;port=parts.port
                if parts.scheme.lower()!='https' or not host or parts.username is not None or parts.password is not None or any(ch in host for ch in '%<>"\''):raise ValueError()
                ascii_host=host.encode('idna').decode('ascii')
                parsed_url=QUrl(url)
                if len(ascii_host)>253 or not parsed_url.isValid() or parsed_url.host().lower()!=ascii_host.lower():raise ValueError()
            except (ValueError,UnicodeError):raise ValueError('Invalid MCP input URL') from None
            forms.append({'id':key,'message':message,'mode':'url','url':url,'host':host,'ascii_host':ascii_host,'port':port});continue
        schema=params.get('requestedSchema')
        if not isinstance(schema,dict):raise ValueError('Invalid MCP input request')
        try:validate_tool_arguments(schema,{})
        except MCPArgumentValidationError:pass
        forms.append({'id':key,'message':message,'mode':'form','schema':schema})
    return {'forms':forms,'request_state':state}


def parse_legacy_request(params,protocol):
    """Validate a 2025 server-initiated form or URL request."""
    if not isinstance(params,dict):raise ValueError('Invalid MCP input request')
    mode=params.get('mode','form')
    if protocol not in ('2025-06-18','2025-11-25') or mode not in ('form','url'):raise ValueError('Unsupported MCP input request')
    if mode=='url':
        ident=params.get('elicitationId')
        if protocol!='2025-11-25' or not isinstance(ident,str) or not ident or len(ident)>256 or any(unicodedata.category(ch).startswith('C') for ch in ident):raise ValueError('Invalid MCP input request')
    pending=parse_input_required({'resultType':'input_required','inputRequests':{'request':{'method':'elicitation/create','params':params}}})
    if mode=='url':pending['forms'][0]['elicitation_id']=ident
    return pending


def track_opened(session,ident):
    """Track only URLs the user opened during the current request."""
    pending=getattr(session,'elicitation_pending',None)
    if not isinstance(ident,str) or not isinstance(pending,dict) or not any(form.get('elicitation_id')==ident for form in pending.get('forms',[])):return
    tracked=session.elicitation_urls
    if ident in tracked:return
    if len(tracked)>=128:tracked.pop(next(iter(tracked)))
    tracked[ident]='open'


def track_completion(session,message):
    """Accept one completion report for a known URL, without trusting its outcome."""
    if not isinstance(message,dict) or message.get('method')!='notifications/elicitation/complete' or 'id' in message:return
    params=message.get('params');ident=params.get('elicitationId') if isinstance(params,dict) else None
    if not isinstance(ident,str) or session.elicitation_urls.get(ident)!='open':return
    session.elicitation_urls[ident]='complete';session.elicitation_completed.emit(ident)
    session.progress.emit('MCP server reports an external interaction completed [untrusted server notification].')


def parse_url_required(error):
    """Validate required external interactions without exposing error data to models."""
    data=error.get('data') if isinstance(error,dict) and error.get('code')==-32042 else None
    items=data.get('elicitations') if isinstance(data,dict) else None
    if not isinstance(items,list) or not items or len(items)>32:raise ValueError('Invalid MCP URL input request')
    try:
        if len(json.dumps(items,ensure_ascii=False,allow_nan=False).encode('utf-8'))>65536:raise ValueError('MCP URL input request too large')
    except (TypeError,UnicodeError,RecursionError):raise ValueError('Invalid MCP URL input request') from None
    forms=[];ids=set()
    for index,params in enumerate(items):
        if not isinstance(params,dict) or params.get('mode')!='url':raise ValueError('Invalid MCP URL input request')
        form=parse_legacy_request(params,'2025-11-25')['forms'][0];ident=params['elicitationId']
        if ident in ids:raise ValueError('Duplicate MCP input request')
        ids.add(ident);form['id']=str(index);forms.append(form)
    return {'forms':forms,'request_state':None,'retry_required':True}


def continuation(original,pending,responses):
    """Validate user responses and build the next explicit protocol round."""
    if not isinstance(original,dict) or not isinstance(original.get('params'),dict) or not isinstance(responses,dict):raise ValueError('Invalid MCP input response')
    forms=pending['forms']
    if set(responses)!={form['id'] for form in forms}:raise ValueError('Incomplete MCP input response')
    for form in forms:
        response=responses[form['id']]
        if not isinstance(response,dict) or response.get('action') not in ('accept','decline','cancel'):raise ValueError('Invalid MCP input response')
        if response['action']=='accept':
            if form.get('mode','form')=='url':
                if set(response)!={'action'}:raise ValueError('Invalid MCP input response')
            else:
                if set(response)!={'action','content'}:raise ValueError('Invalid MCP input response')
                validate_answer(form['schema'],response['content'])
        elif set(response)!={'action'}:raise ValueError('Invalid MCP input response')
    params=dict(original['params']);params.pop('inputResponses',None);params.pop('requestState',None);params['inputResponses']=responses
    if pending['request_state'] is not None:params['requestState']=pending['request_state']
    return dict(original,params=params)


class ElicitationDialog(QDialog):
    """Review server-provided forms without putting answers in the model context."""
    url_opened=Signal(str)
    def __init__(self,server,forms,parent=None,retry_required=False):
        super().__init__(parent);self.forms=forms;self.position=0;self.responses={};self.completed_ids=set();self.retry_required=retry_required;self.retry_confirmation=False;self.retry_confirmed=False;self.setWindowTitle(self.tr('MCP input request'))
        layout=QVBoxLayout(self)
        self.server=server;self.intro=QLabel();self.intro.setWordWrap(True);self.intro.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.intro)
        self.counter=QLabel();layout.addWidget(self.counter)
        self.message=QLabel();self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.message)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1);self.fields={};self.extra={};self.switching=False
        self.form_scroll=QScrollArea();self.form_scroll.setWidgetResizable(True);self.form_widget=QWidget();self.form_layout=QFormLayout(self.form_widget);self.form_scroll.setWidget(self.form_widget)
        self.tabs.addTab(self.form_scroll,self.tr('Form'))
        raw=QWidget();raw_layout=QVBoxLayout(raw);schema_label=QLabel(self.tr('Requested format'));raw_layout.addWidget(schema_label)
        self.schema=QPlainTextEdit();self.schema.setObjectName('mcpElicitationSchema');self.schema.setReadOnly(True);schema_label.setBuddy(self.schema);raw_layout.addWidget(self.schema)
        answer_label=QLabel(self.tr('Your answer as a JSON object'));raw_layout.addWidget(answer_label)
        self.answer=QPlainTextEdit();self.answer.setObjectName('mcpElicitationAnswer');answer_label.setBuddy(self.answer);raw_layout.addWidget(self.answer);self.tabs.addTab(raw,self.tr('JSON'))
        self.tabs.currentChanged.connect(self.switch_view)
        self.url_box=QWidget();url_layout=QVBoxLayout(self.url_box);url_layout.setContentsMargins(0,0,0,0)
        self.url_host=QLabel();self.url_host.setWordWrap(True);self.url_host.setTextFormat(Qt.TextFormat.PlainText);url_layout.addWidget(self.url_host)
        url_label=QLabel(self.tr('Full URL'));url_layout.addWidget(url_label)
        self.url_text=QPlainTextEdit();self.url_text.setObjectName('mcpElicitationUrl');self.url_text.setReadOnly(True);url_label.setBuddy(self.url_text);url_layout.addWidget(self.url_text);layout.addWidget(self.url_box,1)
        self.completion_status=QLabel();self.completion_status.setWordWrap(True);self.completion_status.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.completion_status)
        self.error=QLabel();self.error.setWordWrap(True);self.error.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.error)
        buttons=QDialogButtonBox();self.accept_button=buttons.addButton(self.tr('Send answer'),QDialogButtonBox.ButtonRole.AcceptRole);self.decline_button=buttons.addButton(self.tr('Decline'),QDialogButtonBox.ButtonRole.DestructiveRole);self.cancel_button=buttons.addButton(QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
        self.accept_button.clicked.connect(self.submit);self.decline_button.clicked.connect(self.decline);self.cancel_button.clicked.connect(self.reject);self.show_form()
        screen=self.screen() or QApplication.primaryScreen();area=screen.availableGeometry() if screen else None
        self.resize(min(680,round(area.width()*.9)) if area else 680,min(600,round(area.height()*.9)) if area else 600)

    def show_form(self):
        form=self.forms[self.position];self.message.setText(form['message']);is_url=form.get('mode','form')=='url'
        if is_url:
            self.intro.setText(self.tr('The MCP server {server} requests an external browser interaction. Review the full URL before opening it. Opening the URL signals consent, not completion.').format(server=self.server))
            host=form['host'];ascii_host=form['ascii_host'];domain=host if host==ascii_host else host+' ('+ascii_host+')'
            if host!=ascii_host or any(label.startswith('xn--') for label in ascii_host.lower().split('.')):domain+=' '+self.tr('(internationalized domain)')
            if form['port'] is not None:domain+=':'+str(form['port'])
            self.url_host.setText(self.tr('Destination host: {host}').format(host=domain));self.url_text.setPlainText(form['url'])
        else:
            self.intro.setText(self.tr('The MCP server {server} requests information for the current operation. Your answer will be sent to that server and may be returned to the model in its result. Form input is for non-sensitive information; do not enter passwords or secrets.').format(server=self.server))
            self.schema.setPlainText(json.dumps(form['schema'],indent=2,ensure_ascii=False))
        self.tabs.setVisible(not is_url);self.url_box.setVisible(is_url)
        multiple=len(self.forms)>1;last=self.position==len(self.forms)-1
        self.counter.setVisible(multiple)
        if multiple:self.counter.setText(self.tr('Request {current} of {total}').format(current=self.position+1,total=len(self.forms)))
        self.accept_button.setText(self.tr('Open in browser') if is_url else self.tr('Send answers') if multiple and last else self.tr('Next') if multiple else self.tr('Send answer'))
        self.decline_button.setText(self.tr('Decline and send') if multiple and last else self.tr('Decline and next') if multiple else self.tr('Decline'))
        self.error.clear()
        if not is_url:
            properties=form['schema'].get('properties',{});defaults={key:value['default'] for key,value in properties.items() if isinstance(value,dict) and 'default' in value}
            self.answer.setPlainText(json.dumps(defaults,indent=2,ensure_ascii=False));self.build_form(form['schema'],defaults)

    def build_form(self,schema,values):
        while self.form_layout.rowCount():self.form_layout.removeRow(0)
        self.fields={};self.extra={};properties=schema.get('properties',{})
        simple=not any(key in schema for key in ('$ref','oneOf','anyOf','allOf'))
        for field in properties.values():
            if not isinstance(field,dict) or field.get('type') not in ('string','integer','number','boolean') or any(key in field for key in ('$ref','oneOf','anyOf','allOf')):simple=False;break
            if 'enum' in field and (not field['enum'] or any(type(item) not in (str,int,float,bool) for item in field['enum'])):simple=False;break
        self.switching=True;self.tabs.setTabEnabled(0,simple);self.tabs.setCurrentIndex(0 if simple else 1);self.switching=False
        if not simple:return
        required=set(schema.get('required',[]))
        for name,field in properties.items():
            row=QWidget();row_layout=QHBoxLayout(row);row_layout.setContentsMargins(0,0,0,0);include=None
            if name not in required:
                include=QCheckBox(self.tr('Include'));include.setChecked(name in values);row_layout.addWidget(include)
            enum=field.get('enum')
            if enum is not None or field['type']=='boolean':
                editor=QComboBox();editor.addItem(self.tr('Choose…'),None)
                choices=enum if enum is not None else [True,False];labels=field.get('enumNames',[])
                for index,value in enumerate(choices):
                    label=labels[index] if isinstance(labels,list) and len(labels)==len(choices) and isinstance(labels[index],str) else (self.tr('Yes') if value is True else self.tr('No') if value is False else str(value))
                    editor.addItem(label,value)
            else:editor=QLineEdit()
            editor.setObjectName('mcpElicitationField');editor.setAccessibleName(str(field.get('title') or name));row_layout.addWidget(editor,1)
            if include:editor.setEnabled(include.isChecked());include.toggled.connect(editor.setEnabled)
            title=field.get('title') if isinstance(field.get('title'),str) else name;label=QLabel(title+(' *' if name in required else ''));label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);label.setMaximumWidth(220);label.setBuddy(editor)
            if isinstance(field.get('description'),str):editor.setToolTip('<qt>'+html.escape(field['description'])+'</qt>')
            self.form_layout.addRow(label,row);self.fields[name]=(field,editor,include)
        self.extra_notice=QLabel();self.extra_notice.setTextFormat(Qt.TextFormat.PlainText);self.extra_notice.setWordWrap(True);self.form_layout.addRow(self.extra_notice)
        try:self.load_values(values)
        except (ValueError,TypeError):self.fields={};self.switching=True;self.tabs.setTabEnabled(0,False);self.tabs.setCurrentIndex(1);self.switching=False

    def load_values(self,values):
        for name,(field,editor,_) in self.fields.items():
            if name not in values:continue
            value=values[name];kind=field['type']
            if (kind=='string' and not isinstance(value,str)) or (kind=='integer' and type(value) is not int) or (kind=='number' and type(value) not in (int,float)) or (kind=='boolean' and type(value) is not bool):raise ValueError('Value cannot be represented by the form')
            if type(value) is float and not math.isfinite(value):raise ValueError('Value cannot be represented by the form')
            if isinstance(editor,QComboBox) and not any(type(editor.itemData(i)) is type(value) and editor.itemData(i)==value for i in range(1,editor.count())):raise ValueError('Value cannot be represented by the form')
        self.extra={key:value for key,value in values.items() if key not in self.fields}
        self.extra_notice.setVisible(bool(self.extra))
        if self.extra:
            names=', '.join(str(key)[:60] for key in list(self.extra)[:8]);self.extra_notice.setText(self.tr('Additional JSON fields will also be sent: {fields}').format(fields=names+('…' if len(self.extra)>8 else '')))
        for name,(field,editor,include) in self.fields.items():
            present=name in values
            if include:include.setChecked(present)
            value=values.get(name)
            if isinstance(editor,QComboBox):
                index=next((i for i in range(1,editor.count()) if type(editor.itemData(i)) is type(value) and editor.itemData(i)==value),0);editor.setCurrentIndex(index)
            else:editor.setText('' if not present else str(value))

    def form_values(self,incomplete=False):
        result=dict(self.extra)
        for name,(field,editor,include) in self.fields.items():
            if include and not include.isChecked():continue
            if isinstance(editor,QComboBox):
                if editor.currentIndex()==0:
                    if incomplete:continue
                    raise ValueError(self.tr('Choose a value for {field}.').format(field=name))
                value=editor.currentData()
            elif field['type']=='string':value=editor.text()
            else:
                if incomplete and not editor.text().strip():continue
                try:value=json.loads(editor.text(),parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                except (ValueError,TypeError):raise ValueError(self.tr('Enter a number for {field}.').format(field=name)) from None
                if type(value) not in ((int,) if field['type']=='integer' else (int,float)):raise ValueError(self.tr('Enter a number for {field}.').format(field=name))
            result[name]=value
        return result

    def switch_view(self,index):
        if self.switching:return
        try:
            if index==1:self.answer.setPlainText(json.dumps(self.form_values(incomplete=True),indent=2,ensure_ascii=False,allow_nan=False))
            else:
                raw=self.answer.toPlainText()
                if len(raw.encode('utf-8'))>65536:raise ValueError()
                value=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                if not isinstance(value,dict):raise ValueError()
                json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
                self.load_values(value)
            self.error.clear()
        except (ValueError,TypeError,UnicodeError,RecursionError):
            self.error.setText(self.tr('Enter a JSON object that can be represented by the form.') if index==0 else self.tr('Complete valid form values before switching views.'));self.switching=True;self.tabs.setCurrentIndex(1-index);self.switching=False

    def submit(self):
        if self.retry_confirmation:
            self.retry_confirmed=True;self.accept();return
        form=self.forms[self.position]
        if form.get('mode','form')=='url':
            try:opened=open_elicitation_url(form['url'])
            except Exception:opened=False
            if not opened:
                self.error.setText(self.tr('Could not open the browser. The request was not continued.'));return
            if form.get('elicitation_id'):self.url_opened.emit(form['elicitation_id'])
            self.responses[form['id']]={'action':'accept'};self.position+=1
            if self.position==len(self.forms):self.finish_answers()
            else:self.show_form()
            return
        try:
            if self.tabs.currentIndex()==0:value=self.form_values()
            else:
                raw=self.answer.toPlainText()
                if len(raw.encode('utf-8'))>65536:raise ValueError('Answer is too large.')
                value=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            validate_answer(form['schema'],value)
        except (ValueError,TypeError,UnicodeError,RecursionError) as exc:
            self.error.setText(str(exc)[:500] or self.tr('Enter a valid JSON object.'));return
        self.responses[form['id']]={'action':'accept','content':value};self.position+=1
        if self.position==len(self.forms):self.accept()
        else:self.show_form()

    def decline(self):
        self.responses[self.forms[self.position]['id']]={'action':'decline'};self.position+=1
        if self.position==len(self.forms):self.finish_answers()
        else:self.show_form()

    def finish_answers(self):
        if not self.retry_required or any(response['action']!='accept' for response in self.responses.values()):self.accept();return
        self.retry_confirmation=True;self.tabs.hide();self.url_box.hide();self.counter.hide();self.message.hide();self.decline_button.hide();self.error.clear()
        self.intro.setText(self.tr('Complete the requested interactions in your browser. The previous operation may have performed actions; inspect the server state before retrying. Choose Retry request only when you are ready to submit the operation again.'))
        self.accept_button.setText(self.tr('Retry request'))

    def report_completion(self,ident):
        if ident in self.completed_ids or not any(form.get('elicitation_id')==ident for form in self.forms):return
        self.completed_ids.add(ident)
        total=sum(1 for form in self.forms if form.get('elicitation_id'))
        self.completion_status.setText(self.tr('The server reports {completed} of {total} external steps complete. This is an untrusted server report.').format(completed=len(self.completed_ids),total=total))

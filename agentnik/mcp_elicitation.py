"""Validate and present MCP form elicitation requests."""
import json
import html
import math
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPlainTextEdit,QDialogButtonBox,QTabWidget,QWidget,QScrollArea,QLineEdit,QComboBox,QCheckBox)
from .mcp_schema import validate_tool_arguments,MCPArgumentValidationError


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
    """Extract supported, non-sensitive form requests and opaque continuation state."""
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
        if not isinstance(params,dict) or params.get('mode','form')!='form':raise ValueError('Unsupported MCP input request')
        message=params.get('message');schema=params.get('requestedSchema')
        if not isinstance(message,str) or not message or len(message)>8000 or not isinstance(schema,dict):raise ValueError('Invalid MCP input request')
        try:validate_tool_arguments(schema,{})
        except MCPArgumentValidationError:pass
        forms.append({'id':key,'message':message,'schema':schema})
    return {'forms':forms,'request_state':state}


def continuation(original,pending,responses):
    """Validate user responses and build the next explicit protocol round."""
    if not isinstance(original,dict) or not isinstance(original.get('params'),dict) or not isinstance(responses,dict):raise ValueError('Invalid MCP input response')
    forms=pending['forms']
    if set(responses)!={form['id'] for form in forms}:raise ValueError('Incomplete MCP input response')
    for form in forms:
        response=responses[form['id']]
        if not isinstance(response,dict) or response.get('action') not in ('accept','decline','cancel'):raise ValueError('Invalid MCP input response')
        if response['action']=='accept':
            if set(response)!={'action','content'}:raise ValueError('Invalid MCP input response')
            validate_answer(form['schema'],response['content'])
        elif set(response)!={'action'}:raise ValueError('Invalid MCP input response')
    params=dict(original['params']);params.pop('inputResponses',None);params.pop('requestState',None);params['inputResponses']=responses
    if pending['request_state'] is not None:params['requestState']=pending['request_state']
    return dict(original,params=params)


class ElicitationDialog(QDialog):
    """Review server-provided forms without putting answers in the model context."""
    def __init__(self,server,forms,parent=None):
        super().__init__(parent);self.forms=forms;self.position=0;self.responses={};self.setWindowTitle(self.tr('MCP input request'))
        layout=QVBoxLayout(self)
        intro=QLabel(self.tr('The MCP server {server} requests information for the current operation. Your answer will be sent to that server and may be returned to the model in its result. Form input is for non-sensitive information; do not enter passwords or secrets.').format(server=server));intro.setWordWrap(True);intro.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(intro)
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
        self.error=QLabel();self.error.setWordWrap(True);self.error.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.error)
        buttons=QDialogButtonBox();self.accept_button=buttons.addButton(self.tr('Send answer'),QDialogButtonBox.ButtonRole.AcceptRole);self.decline_button=buttons.addButton(self.tr('Decline'),QDialogButtonBox.ButtonRole.DestructiveRole);self.cancel_button=buttons.addButton(QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
        self.accept_button.clicked.connect(self.submit);self.decline_button.clicked.connect(self.decline);self.cancel_button.clicked.connect(self.reject);self.show_form()
        screen=self.screen() or QApplication.primaryScreen();area=screen.availableGeometry() if screen else None
        self.resize(min(680,round(area.width()*.9)) if area else 680,min(600,round(area.height()*.9)) if area else 600)

    def show_form(self):
        form=self.forms[self.position];self.message.setText(form['message']);self.schema.setPlainText(json.dumps(form['schema'],indent=2,ensure_ascii=False))
        multiple=len(self.forms)>1;last=self.position==len(self.forms)-1
        self.counter.setVisible(multiple)
        if multiple:self.counter.setText(self.tr('Request {current} of {total}').format(current=self.position+1,total=len(self.forms)))
        self.accept_button.setText(self.tr('Send answers') if multiple and last else self.tr('Next') if multiple else self.tr('Send answer'))
        self.decline_button.setText(self.tr('Decline and send') if multiple and last else self.tr('Decline and next') if multiple else self.tr('Decline'))
        properties=form['schema'].get('properties',{});defaults={key:value['default'] for key,value in properties.items() if isinstance(value,dict) and 'default' in value}
        self.answer.setPlainText(json.dumps(defaults,indent=2,ensure_ascii=False));self.error.clear();self.build_form(form['schema'],defaults)

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
        form=self.forms[self.position]
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
        if self.position==len(self.forms):self.accept()
        else:self.show_form()

"""Validate and present MCP form elicitation requests."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QLabel,QPlainTextEdit,QDialogButtonBox
from .mcp_schema import validate_tool_arguments,MCPArgumentValidationError


def validate_answer(schema,value):
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
        schema_label=QLabel(self.tr('Requested format'));layout.addWidget(schema_label)
        self.schema=QPlainTextEdit();self.schema.setObjectName('mcpElicitationSchema');self.schema.setReadOnly(True);schema_label.setBuddy(self.schema);layout.addWidget(self.schema)
        answer_label=QLabel(self.tr('Your answer as a JSON object'));layout.addWidget(answer_label)
        self.answer=QPlainTextEdit();self.answer.setObjectName('mcpElicitationAnswer');answer_label.setBuddy(self.answer);layout.addWidget(self.answer)
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
        self.answer.setPlainText(json.dumps(defaults,indent=2,ensure_ascii=False));self.error.clear()

    def submit(self):
        form=self.forms[self.position]
        try:
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

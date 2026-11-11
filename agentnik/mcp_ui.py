"""MCP server manager and explicitly initiated local connection preview."""
import json
import uuid
from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QCheckBox,QPushButton,QListWidget,QMessageBox,QComboBox,QDialogButtonBox)
from .mcp_support import MAX_OUTPUT,validate_servers,initialize_request,parse_initialize


class MCPServers(QDialog):
    def __init__(self,window):
        super().__init__(window);self.store=window.store;self.setWindowTitle(self.tr('MCP servers'));self.resize(680,520)
        self.process=None;self.remote=None;self.validation_job=None;self._closed=False;self.discovered=None;self.discovered_config=None;self.buffer=bytearray();self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.finish_test('Connection test timed out.'))
        layout=QVBoxLayout(self);layout.addWidget(QLabel(self.tr('Servers can access your data. Local commands and arguments are stored in plaintext; do not put secrets in them.')))
        self.list=QListWidget();layout.addWidget(self.list);self.list.currentRowChanged.connect(self.load_row)
        form=QFormLayout();layout.addLayout(form);self.name=QLineEdit();self.transport=QComboBox();self.transport.addItems(['Local stdio','Remote HTTPS']);self.command=QLineEdit();self.args=QPlainTextEdit();self.args.setPlaceholderText('["argument", "argument"]');self.args.setMaximumHeight(80);self.url=QLineEdit();self.url.setPlaceholderText('https://mcp.parallel.ai/mcp');self.token=QLineEdit();self.token.setEchoMode(QLineEdit.EchoMode.Password);self.token.setPlaceholderText(self.tr('Leave blank to keep the saved credential'));self.enabled=QCheckBox(self.tr('Enabled'));self.enabled.setChecked(True)
        form.addRow(self.tr('Name'),self.name);form.addRow(self.tr('Transport'),self.transport);form.addRow(self.tr('Executable'),self.command);form.addRow(self.tr('Arguments (JSON array)'),self.args);form.addRow(self.tr('HTTPS URL'),self.url);form.addRow(self.tr('Bearer token'),self.token);form.addRow('',self.enabled)
        row=QHBoxLayout();layout.addLayout(row)
        for label,handler in ((self.tr('New'),self.new),(self.tr('Save'),self.save),(self.tr('Remove'),self.remove),(self.tr('Test connection'),self.test)):
            button=QPushButton(label);button.clicked.connect(handler);row.addWidget(button)
        self.status=QLabel(self.tr('No server has been tested.'));self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);layout.addWidget(self.status)
        layout.addWidget(QLabel(self.tr('Discovered tools (server-provided, untrusted):')))
        self.tool_details=QPlainTextEdit();self.tool_details.setReadOnly(True);self.tool_details.setPlaceholderText(self.tr('Test a server to inspect its tools.'));layout.addWidget(self.tool_details)
        callrow=QHBoxLayout();layout.addLayout(callrow);callrow.addWidget(QLabel(self.tr('Tool:')));self.tool_choice=QComboBox();callrow.addWidget(self.tool_choice)
        callbutton=QPushButton(self.tr('Review and call…'));callbutton.clicked.connect(self.call_remote);callrow.addWidget(callbutton)
        layout.addWidget(QLabel(self.tr('Tool arguments (JSON object):')));self.tool_args=QPlainTextEdit();self.tool_args.setPlainText('{}');self.tool_args.setMaximumHeight(100);layout.addWidget(self.tool_args)
        layout.addWidget(QLabel(self.tr('Tool result (untrusted):')));self.tool_result=QPlainTextEdit();self.tool_result.setReadOnly(True);layout.addWidget(self.tool_result)
        self.populate()

    def populate(self):
        self.list.clear()
        for server in self.store.config.get('mcp_servers',[]):self.list.addItem(server['name']+('' if server['enabled'] else ' (disabled)'))

    def new(self):
        self.list.setCurrentRow(-1);self.name.clear();self.transport.setCurrentIndex(0);self.command.clear();self.args.setPlainText('[]');self.url.clear();self.token.clear();self.enabled.setChecked(True)

    def load_row(self,index):
        if self.process:self.finish_test('Local MCP session closed.')
        self.tool_details.clear();self.tool_choice.clear();self.tool_result.clear();self.discovered=None
        entries=self.store.config.get('mcp_servers',[])
        if 0<=index<len(entries):
            item=entries[index];remote=item.get('transport')=='http';self.name.setText(item['name']);self.transport.setCurrentIndex(1 if remote else 0);self.command.setText(item.get('command',''));self.args.setPlainText(json.dumps(item.get('args',[]),ensure_ascii=False));self.url.setText(item.get('url',''));self.token.clear();self.enabled.setChecked(item['enabled'])

    def save(self):
        try:
            entries=list(self.store.config.get('mcp_servers',[]));index=self.list.currentRow()
            prior=entries[index] if 0<=index<len(entries) else {};old_id=prior.get('credential_id','');new_id=''
            if self.transport.currentIndex()==1:
                url=self.url.text().strip();token=self.token.text()
                if token and (len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token)):raise ValueError('Bearer token must be a single visible ASCII token')
                credential=old_id if prior.get('url')==url else ''
                if token:credential=uuid.uuid4().hex;new_id=credential
                item={'name':self.name.text().strip(),'transport':'http','url':url,'credential_id':credential,'enabled':self.enabled.isChecked()}
            else:item={'name':self.name.text().strip(),'command':self.command.text().strip(),'args':json.loads(self.args.toPlainText() or '[]'),'enabled':self.enabled.isChecked()}
            if index<0:entries.append(item);index=len(entries)-1
            else:entries[index]=item
            validate_servers(entries)
            if new_id:
                import keyring
                keyring.set_password('Agentnik',new_id,token)
            old=self.store.config.get('mcp_servers');self.store.config['mcp_servers']=entries
            try:self.store.flush()
            except Exception:
                if old is None:self.store.config.pop('mcp_servers',None)
                else:self.store.config['mcp_servers']=old
                if new_id:
                    try:keyring.delete_password('Agentnik',new_id)
                    except Exception:pass
                raise
            if old_id and old_id!=item.get('credential_id',''):
                import keyring
                try:keyring.delete_password('Agentnik',old_id)
                except Exception:pass
        except Exception:QMessageBox.warning(self,self.tr('MCP servers'),self.tr('Could not save the server. Check its settings and credential store.'));return
        self.populate();self.list.setCurrentRow(index);self.status.setText(self.tr('Saved. No server was started.'))

    def remove(self):
        index=self.list.currentRow();entries=list(self.store.config.get('mcp_servers',[]))
        if not 0<=index<len(entries):return
        if QMessageBox.question(self,self.tr('MCP servers'),self.tr('Remove this server configuration?'))!=QMessageBox.StandardButton.Yes:return
        old=entries[:];entries.pop(index);self.store.config['mcp_servers']=entries
        try:self.store.flush()
        except OSError:self.store.config['mcp_servers']=old;QMessageBox.warning(self,self.tr('MCP servers'),self.tr('Could not save the configuration.'));return
        if old[index].get('credential_id'):
            import keyring
            try:keyring.delete_password('Agentnik',old[index]['credential_id'])
            except Exception:pass
        self.populate();self.new()

    def test(self):
        entries=self.store.config.get('mcp_servers',[]);index=self.list.currentRow()
        if self.process or self.remote or not 0<=index<len(entries):return
        item=entries[index]
        if not item['enabled']:self.status.setText(self.tr('Enable and save this server before testing.'));return
        self.tool_details.clear();self.tool_choice.clear();self.tool_result.clear();self.discovered=None
        if item.get('transport')=='http':self.test_remote(item);return
        details=self.tr('Start this local program with your user permissions?\n\nExecutable: {command}\nArguments: {args}\n\nThe server can access your files and network.').format(command=item['command'],args=json.dumps(item['args'],ensure_ascii=False))
        if QMessageBox.question(self,self.tr('Test MCP server'),details,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        from .mcp_local import LocalSession
        self.discovered_config=dict(item);self.process=LocalSession(item['command'],item['args'],self)
        self.process.discovered.connect(self.local_discovered);self.process.called.connect(self.local_called);self.process.ended.connect(self.local_ended)
        self.status.setText(self.tr('Connecting…'));self.process.start()

    def local_discovered(self,result):
        self.remote_done(result)
        self.status.setText(self.status.text()+' · local session active')

    def local_called(self,result):
        if 'error' in result:self.status.setText(result['error']);return
        self.tool_result.setPlainText(json.dumps(result.get('call_result',{}),ensure_ascii=True,indent=2))
        self.status.setText(self.tr('Tool returned an error.' if result.get('call_result',{}).get('isError') else 'Tool call completed.'))

    def local_ended(self,result):
        session=self.process;self.process=None
        if session:session.deleteLater()
        self.discovered=None;self.tool_choice.clear()
        self.status.setText(result['error']+(' The call may have completed; inspect server state before retrying.' if result.get('call_uncertain') else ''))

    def finish_test(self,message):
        process=self.process
        if process is None:return
        self.process=None;process.close();process.deleteLater();self.discovered=None;self.status.setText(message)

    def done(self,result):
        self._closed=True
        if self.validation_job:self.validation_job.cancel.set()
        if self.process:self.finish_test('Connection test cancelled.')
        if self.remote:self.remote.stop()
        super().done(result)

    def test_remote(self,item):
        details=self.tr('Connect to this MCP server and send a discovery request?\n\n{url}\n\nIts operator receives the request and any configured bearer token.').format(url=item['url'])
        if QMessageBox.question(self,self.tr('Test MCP server'),details,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        token=''
        if item.get('credential_id'):
            try:
                import keyring
                token=keyring.get_password('Agentnik',item['credential_id']) or ''
            except Exception:token=''
            if not token:self.status.setText(self.tr('MCP credential is unavailable in the credential store.'));return
            if len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token):self.status.setText(self.tr('MCP credential has an invalid format.'));return
        from .mcp_remote import RemoteProbe
        self.discovered_config=dict(item);self.remote=RemoteProbe(item['url'],token,self);self.remote.finished.connect(self.remote_done);self.status.setText(self.tr('Connecting…'));self.remote.start()

    def remote_done(self,result):
        probe=self.remote;self.remote=None
        if probe:probe.deleteLater()
        if 'error' in result:self.status.setText(result['error']);return
        self.discovered={'config':self.discovered_config,'tools':result.get('tool_details',[])}
        self.tool_choice.clear();self.tool_choice.addItems([item['name'] for item in self.discovered['tools']])
        self.status.setText('Connected: '+result['name']+' '+result['version']+' · MCP '+result['protocol']+' · tools: '+(', '.join(result.get('tools',[])) or 'none')+(' (more available)' if result.get('more_tools') else '')+(' · session close not confirmed' if result.get('session_closed') is False else ''))
        sections=[]
        for detail in result.get('tool_details',[]):
            description=detail['description'] or '(no description)'
            if detail['description_clipped']:description+='\n[Description truncated or unavailable]'
            schema=json.dumps(detail['schema'],ensure_ascii=True,indent=2) if detail['schema_status']=='available' else '[Input schema '+detail['schema_status']+']'
            sections.append(detail['name']+'\n'+description+'\nInput schema:\n'+schema)
        self.tool_details.setPlainText('\n\n'.join(sections))

    def call_remote(self):
        if self.remote or self.validation_job or not self.discovered:return
        index=self.list.currentRow();entries=self.store.config.get('mcp_servers',[])
        if not 0<=index<len(entries) or entries[index]!=self.discovered['config']:
            self.status.setText(self.tr('Server configuration changed. Test it again.'));return
        item=entries[index];tool=next((tool for tool in self.discovered['tools'] if tool['name']==self.tool_choice.currentText()),None)
        if not tool or tool['schema_status']!='available' or tool['description_clipped']:self.status.setText(self.tr('This tool has incomplete metadata and cannot be called.'));return
        try:
            raw=self.tool_args.toPlainText()
            if len(raw.encode('utf-8'))>16000:raise ValueError()
            args=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if not isinstance(args,dict):raise ValueError()
            json.dumps(args,allow_nan=False)
        except (ValueError,UnicodeError,RecursionError):self.status.setText(self.tr('Enter a JSON object of at most 16 KB.'));return
        from .mcp_schema import validate_tool_arguments
        from .ui import Job
        self.status.setText(self.tr('Validating tool arguments…'))
        def work(progress,cancel):
            if cancel.is_set():return False
            return validate_tool_arguments(tool['schema'],args)
        self.validation_job=Job(work,lambda valid:self.validated_call(valid,index,dict(item),tool,args,raw),self.validation_failed)

    def validation_failed(self,message):
        self.validation_job=None
        if not self._closed:self.status.setText(message)

    def validated_call(self,valid,index,item,tool,args,raw):
        self.validation_job=None
        if self._closed or not valid:return
        entries=self.store.config.get('mcp_servers',[])
        if self.list.currentRow()!=index or not 0<=index<len(entries) or entries[index]!=item or not self.discovered or item!=self.discovered['config'] or self.tool_choice.currentText()!=tool['name'] or self.tool_args.toPlainText()!=raw:
            self.status.setText(self.tr('Server, tool, or arguments changed. Review and try again.'));return
        token=''
        if item.get('credential_id'):
            try:
                import keyring
                token=keyring.get_password('Agentnik',item['credential_id']) or ''
            except Exception:token=''
            if not token or len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token):self.status.setText(self.tr('MCP credential is unavailable or invalid.'));return
            if token in json.dumps(args,ensure_ascii=False):self.status.setText(self.tr('Arguments contain the configured credential.'));return
        review=QDialog(self);review.setWindowTitle(self.tr('Review MCP tool call'));review.resize(720,540);layout=QVBoxLayout(review)
        layout.addWidget(QLabel(self.tr('The server receives these arguments and may perform external actions.')))
        preview=QPlainTextEdit();preview.setReadOnly(True);preview.setPlainText('Server: '+item['name']+'\nDestination: '+(item['url'] if item.get('transport')=='http' else item['command']+' '+json.dumps(item['args'],ensure_ascii=True))+'\nTool: '+tool['name']+'\n\nDescription:\n'+tool['description']+'\n\nInput schema:\n'+json.dumps(tool['schema'],ensure_ascii=True,indent=2)+'\n\nArguments:\n'+json.dumps(args,ensure_ascii=True,indent=2));layout.addWidget(preview)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(review.accept);buttons.rejected.connect(review.reject);layout.addWidget(buttons)
        if review.exec()!=QDialog.DialogCode.Accepted:return
        if self.list.currentRow()!=index or self.store.config.get('mcp_servers',[])!=entries or self.discovered is None or entries[index]!=self.discovered['config']:
            self.status.setText(self.tr('Server configuration changed. Test it again.'));return
        if item.get('transport')!='http':
            if not self.process or not self.process.call(tool,args):self.status.setText(self.tr('Local MCP session is no longer available.'));return
            self.tool_result.clear();self.status.setText(self.tr('Calling tool…'));return
        from .mcp_remote import RemoteProbe
        self.tool_result.clear();self.remote=RemoteProbe(item['url'],token,self,invocation={'tool':tool,'arguments':args});self.remote.finished.connect(self.call_done);self.status.setText(self.tr('Calling tool…'));self.remote.start()

    def call_done(self,result):
        probe=self.remote;self.remote=None
        if probe:probe.deleteLater()
        if 'error' in result:
            self.status.setText(result['error']+(' The call may have reached the server; inspect its state before retrying.' if result.get('call_uncertain') else ''));return
        self.tool_result.setPlainText(json.dumps(result.get('call_result',{}),ensure_ascii=True,indent=2));self.status.setText(self.tr('Tool returned an error.' if result.get('call_result',{}).get('isError') else 'Tool call completed.')+(' Session close not confirmed.' if result.get('session_closed') is False else ''))

"""MCP server manager and explicitly initiated local connection preview."""
import json
import uuid
from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QCheckBox,QPushButton,QListWidget,QMessageBox,QComboBox)
from .mcp_support import MAX_OUTPUT,validate_servers,initialize_request,parse_initialize


class MCPServers(QDialog):
    def __init__(self,window):
        super().__init__(window);self.store=window.store;self.setWindowTitle(self.tr('MCP servers'));self.resize(680,520)
        self.process=None;self.remote=None;self.buffer=bytearray();self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.finish_test('Connection test timed out.'))
        layout=QVBoxLayout(self);layout.addWidget(QLabel(self.tr('Servers can access your data. Local commands and arguments are stored in plaintext; do not put secrets in them.')))
        self.list=QListWidget();layout.addWidget(self.list);self.list.currentRowChanged.connect(self.load_row)
        form=QFormLayout();layout.addLayout(form);self.name=QLineEdit();self.transport=QComboBox();self.transport.addItems(['Local stdio','Remote HTTPS']);self.command=QLineEdit();self.args=QPlainTextEdit();self.args.setPlaceholderText('["argument", "argument"]');self.args.setMaximumHeight(80);self.url=QLineEdit();self.url.setPlaceholderText('https://mcp.parallel.ai/mcp');self.token=QLineEdit();self.token.setEchoMode(QLineEdit.EchoMode.Password);self.token.setPlaceholderText(self.tr('Leave blank to keep the saved credential'));self.enabled=QCheckBox(self.tr('Enabled'));self.enabled.setChecked(True)
        form.addRow(self.tr('Name'),self.name);form.addRow(self.tr('Transport'),self.transport);form.addRow(self.tr('Executable'),self.command);form.addRow(self.tr('Arguments (JSON array)'),self.args);form.addRow(self.tr('HTTPS URL'),self.url);form.addRow(self.tr('Bearer token'),self.token);form.addRow('',self.enabled)
        row=QHBoxLayout();layout.addLayout(row)
        for label,handler in ((self.tr('New'),self.new),(self.tr('Save'),self.save),(self.tr('Remove'),self.remove),(self.tr('Test connection'),self.test)):
            button=QPushButton(label);button.clicked.connect(handler);row.addWidget(button)
        self.status=QLabel(self.tr('No server has been tested.'));self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);layout.addWidget(self.status)
        layout.addWidget(QLabel(self.tr('Discovered tools (server-provided, untrusted):')))
        self.tool_details=QPlainTextEdit();self.tool_details.setReadOnly(True);self.tool_details.setPlaceholderText(self.tr('Test a remote server to inspect its tools.'));layout.addWidget(self.tool_details)
        self.populate()

    def populate(self):
        self.list.clear()
        for server in self.store.config.get('mcp_servers',[]):self.list.addItem(server['name']+('' if server['enabled'] else ' (disabled)'))

    def new(self):
        self.list.setCurrentRow(-1);self.name.clear();self.transport.setCurrentIndex(0);self.command.clear();self.args.setPlainText('[]');self.url.clear();self.token.clear();self.enabled.setChecked(True)

    def load_row(self,index):
        self.tool_details.clear()
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
        self.tool_details.clear()
        if item.get('transport')=='http':self.test_remote(item);return
        details=self.tr('Start this local program with your user permissions?\n\nExecutable: {command}\nArguments: {args}\n\nThe server can access your files and network.').format(command=item['command'],args=json.dumps(item['args'],ensure_ascii=False))
        if QMessageBox.question(self,self.tr('Test MCP server'),details,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.buffer=bytearray();self.process=QProcess(self);self.process.setProgram(item['command']);self.process.setArguments(item['args']);self.process.readyReadStandardOutput.connect(self.read_output);self.process.readyReadStandardError.connect(lambda:self.process and self.process.readAllStandardError());self.process.errorOccurred.connect(lambda _:self.finish_test('Unable to start or communicate with server.'));self.process.finished.connect(lambda *_:self.finish_test('Server exited before initialization completed.'));self.process.started.connect(self.started);self.status.setText(self.tr('Connecting…'));self.timer.start(10000);self.process.start()

    def started(self):
        if self.process:self.process.write((json.dumps(initialize_request())+'\n').encode())

    def read_output(self):
        if not self.process:return
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer)>MAX_OUTPUT:self.finish_test('Server response exceeded the output limit.');return
        if b'\n' not in self.buffer:return
        line=bytes(self.buffer).split(b'\n',1)[0]
        try:info=parse_initialize(line)
        except ValueError as exc:self.finish_test(str(exc));return
        self.finish_test('Initialization response: '+info['name']+' '+info['version']+' · MCP '+info['protocol']+' · capabilities: '+(', '.join(info['capabilities']) or 'none'))

    def finish_test(self,message):
        process=self.process
        if process is None:return
        self.process=None;self.timer.stop();process.kill();process.waitForFinished(1000);process.deleteLater();self.status.setText(message)

    def done(self,result):
        if self.process:self.finish_test('Connection test cancelled.')
        if self.remote:self.remote.stop()
        super().done(result)

    def test_remote(self,item):
        details=self.tr('Connect to this MCP server and send a discovery request?\n\n{url}\n\nIts operator receives the request and any configured bearer token.').format(url=item['url'])
        if QMessageBox.question(self,self.tr('Test MCP server'),details,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        token=''
        if item['credential_id']:
            try:
                import keyring
                token=keyring.get_password('Agentnik',item['credential_id']) or ''
            except Exception:token=''
            if not token:self.status.setText(self.tr('MCP credential is unavailable in the credential store.'));return
            if len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token):self.status.setText(self.tr('MCP credential has an invalid format.'));return
        from .mcp_remote import RemoteProbe
        self.remote=RemoteProbe(item['url'],token,self);self.remote.finished.connect(self.remote_done);self.status.setText(self.tr('Connecting…'));self.remote.start()

    def remote_done(self,result):
        probe=self.remote;self.remote=None
        if probe:probe.deleteLater()
        if 'error' in result:self.status.setText(result['error']);return
        self.status.setText('Connected: '+result['name']+' '+result['version']+' · MCP '+result['protocol']+' · tools: '+(', '.join(result.get('tools',[])) or 'none')+(' (more available)' if result.get('more_tools') else '')+(' · session close not confirmed' if result.get('session_closed') is False else ''))
        sections=[]
        for detail in result.get('tool_details',[]):
            description=detail['description'] or '(no description)'
            if detail['description_clipped']:description+='\n[Description truncated or unavailable]'
            schema=json.dumps(detail['schema'],ensure_ascii=True,indent=2) if detail['schema_status']=='available' else '[Input schema '+detail['schema_status']+']'
            sections.append(detail['name']+'\n'+description+'\nInput schema:\n'+schema)
        self.tool_details.setPlainText('\n\n'.join(sections))

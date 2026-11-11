"""MCP server manager and explicitly initiated local connection preview."""
import json
from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QCheckBox,QPushButton,QListWidget,QMessageBox)
from .mcp_support import MAX_OUTPUT,validate_servers,initialize_request,parse_initialize


class MCPServers(QDialog):
    def __init__(self,window):
        super().__init__(window);self.store=window.store;self.setWindowTitle(self.tr('MCP servers'));self.resize(680,520)
        self.process=None;self.buffer=bytearray();self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.finish_test('Connection test timed out.'))
        layout=QVBoxLayout(self);layout.addWidget(QLabel(self.tr('Local stdio preview. Servers can run commands and access your data. Do not put secrets in arguments.')))
        self.list=QListWidget();layout.addWidget(self.list);self.list.currentRowChanged.connect(self.load_row)
        form=QFormLayout();layout.addLayout(form);self.name=QLineEdit();self.command=QLineEdit();self.args=QPlainTextEdit();self.args.setPlaceholderText('["argument", "argument"]');self.args.setMaximumHeight(80);self.enabled=QCheckBox(self.tr('Enabled'));self.enabled.setChecked(True)
        form.addRow(self.tr('Name'),self.name);form.addRow(self.tr('Executable'),self.command);form.addRow(self.tr('Arguments (JSON array)'),self.args);form.addRow('',self.enabled)
        row=QHBoxLayout();layout.addLayout(row)
        for label,handler in ((self.tr('New'),self.new),(self.tr('Save'),self.save),(self.tr('Remove'),self.remove),(self.tr('Test connection'),self.test)):
            button=QPushButton(label);button.clicked.connect(handler);row.addWidget(button)
        self.status=QLabel(self.tr('No server has been tested.'));self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);layout.addWidget(self.status)
        self.populate()

    def populate(self):
        self.list.clear()
        for server in self.store.config.get('mcp_servers',[]):self.list.addItem(server['name']+('' if server['enabled'] else ' (disabled)'))

    def new(self):
        self.list.setCurrentRow(-1);self.name.clear();self.command.clear();self.args.setPlainText('[]');self.enabled.setChecked(True)

    def load_row(self,index):
        entries=self.store.config.get('mcp_servers',[])
        if 0<=index<len(entries):
            item=entries[index];self.name.setText(item['name']);self.command.setText(item['command']);self.args.setPlainText(json.dumps(item['args'],ensure_ascii=False));self.enabled.setChecked(item['enabled'])

    def save(self):
        try:
            item={'name':self.name.text().strip(),'command':self.command.text().strip(),'args':json.loads(self.args.toPlainText() or '[]'),'enabled':self.enabled.isChecked()}
            entries=list(self.store.config.get('mcp_servers',[]));index=self.list.currentRow()
            if index<0:entries.append(item);index=len(entries)-1
            else:entries[index]=item
            validate_servers(entries);old=self.store.config.get('mcp_servers');self.store.config['mcp_servers']=entries
            try:self.store.flush()
            except Exception:
                if old is None:self.store.config.pop('mcp_servers',None)
                else:self.store.config['mcp_servers']=old
                raise
        except (ValueError,OSError,TypeError,RecursionError) as exc:QMessageBox.warning(self,self.tr('MCP servers'),str(exc));return
        self.populate();self.list.setCurrentRow(index);self.status.setText(self.tr('Saved. No server was started.'))

    def remove(self):
        index=self.list.currentRow();entries=list(self.store.config.get('mcp_servers',[]))
        if not 0<=index<len(entries):return
        if QMessageBox.question(self,self.tr('MCP servers'),self.tr('Remove this server configuration?'))!=QMessageBox.StandardButton.Yes:return
        old=entries[:];entries.pop(index);self.store.config['mcp_servers']=entries
        try:self.store.flush()
        except OSError:self.store.config['mcp_servers']=old;QMessageBox.warning(self,self.tr('MCP servers'),self.tr('Could not save the configuration.'));return
        self.populate();self.new()

    def test(self):
        entries=self.store.config.get('mcp_servers',[]);index=self.list.currentRow()
        if self.process or not 0<=index<len(entries):return
        item=entries[index]
        if not item['enabled']:self.status.setText(self.tr('Enable and save this server before testing.'));return
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
        super().done(result)

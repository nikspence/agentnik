"""MCP server manager and explicitly initiated local connection preview."""
import json
import uuid
from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QCheckBox,QPushButton,QListWidget,QMessageBox,QComboBox,QDialogButtonBox,QSpinBox,QScrollArea,QWidget,QFileDialog,QInputDialog)
from .mcp_support import MAX_OUTPUT,validate_servers,initialize_request,parse_initialize,server_timeout,DEFAULT_TIMEOUT_SECONDS,MAX_TIMEOUT_SECONDS


class MCPServers(QDialog):
    def __init__(self,window):
        super().__init__(window);self.store=window.store;self.setWindowTitle(self.tr('MCP servers'));self.resize(680,520)
        self.process=None;self.remote=None;self.elicitation_dialog=None;self.oauth_pending=None;self.oauth_discovery=None;self.oauth_authorization=None;self.oauth_metadata=None;self.oauth_config=None;self.oauth_challenge=None;self.oauth_challenge_url=None;self.validation_job=None;self.call_tool=None;self._closed=False;self.discovered=None;self.discovered_config=None;self.buffer=bytearray();self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.finish_test(self.tr('Connection test timed out.')))
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setObjectName('mcpSettingsScroll');scroll.setWidgetResizable(True);outer.addWidget(scroll)
        content=QWidget();scroll.setWidget(content);layout=QVBoxLayout(content)
        notice=QLabel(self.tr('Servers can access your data. Local commands and arguments are stored in plaintext; do not put secrets in them.'));notice.setWordWrap(True);layout.addWidget(notice)
        self.list=QListWidget();layout.addWidget(self.list);self.list.currentRowChanged.connect(self.load_row)
        form=QFormLayout();layout.addLayout(form);self.name=QLineEdit();self.transport=QComboBox();self.transport.addItems([self.tr('Local stdio'),self.tr('Remote HTTPS')]);self.command=QLineEdit();self.args=QPlainTextEdit();self.args.setPlaceholderText('["argument", "argument"]');self.args.setMaximumHeight(80);self.env=QPlainTextEdit();self.env.setPlaceholderText('{"TARGET_NAME": "EXISTING_ENV_NAME"}');self.env.setMaximumHeight(70);self.env.setToolTip(self.tr('Map environment variable names to existing variables in Agentnik’s environment. Values are never stored in settings.'));self.url=QLineEdit();self.url.setPlaceholderText('https://mcp.parallel.ai/mcp');self.token=QLineEdit();self.token.setEchoMode(QLineEdit.EchoMode.Password);self.token.setPlaceholderText(self.tr('Leave blank to keep the saved credential'));self.enabled=QCheckBox(self.tr('Enabled'));self.enabled.setChecked(True)
        self.timeout=QSpinBox();self.timeout.setObjectName('mcpTimeout');self.timeout.setRange(1,MAX_TIMEOUT_SECONDS);self.timeout.setValue(DEFAULT_TIMEOUT_SECONDS);self.timeout.setSuffix(self.tr(' seconds'));self.timeout.setToolTip(self.tr('Maximum time for an MCP operation, including discovery or tool verification. Coding run limits may end it sooner.'))
        self.working_directory=QLineEdit();self.working_directory.setObjectName('mcpWorkingDirectory');self.working_directory.setPlaceholderText(self.tr('Optional absolute path; blank uses Agentnik working directory'))
        self.working_directory_button=QPushButton(self.tr('Browse…'));self.working_directory_button.clicked.connect(self.choose_working_directory)
        directory_row=QHBoxLayout();directory_row.addWidget(self.working_directory);directory_row.addWidget(self.working_directory_button)
        self.transport.currentIndexChanged.connect(lambda index:(self.working_directory.setEnabled(index==0),self.working_directory_button.setEnabled(index==0)))
        form.addRow(self.tr('Name'),self.name);form.addRow(self.tr('Transport'),self.transport);form.addRow(self.tr('Executable'),self.command);form.addRow(self.tr('Arguments (JSON array)'),self.args);form.addRow(self.tr('Working directory'),directory_row);form.addRow(self.tr('Environment names (JSON object)'),self.env);form.addRow(self.tr('HTTPS URL'),self.url);form.addRow(self.tr('Bearer token'),self.token);form.addRow(self.tr('Operation timeout'),self.timeout);form.addRow('',self.enabled)
        row=QHBoxLayout();layout.addLayout(row)
        for label,handler in ((self.tr('New'),self.new),(self.tr('Save'),self.save),(self.tr('Remove'),self.remove)):
            button=QPushButton(label);button.clicked.connect(handler);row.addWidget(button)
        row.addStretch();connection_row=QHBoxLayout();layout.addLayout(connection_row)
        for label,handler in ((self.tr('Test connection'),self.test),(self.tr('Discover sign-in'),self.discover_oauth)):
            button=QPushButton(label);button.clicked.connect(handler);connection_row.addWidget(button)
        self.oauth_button=QPushButton(self.tr('Sign in…'));self.oauth_button.setEnabled(False);self.oauth_button.clicked.connect(self.sign_in_oauth);connection_row.addWidget(self.oauth_button)
        connection_row.addStretch()
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
        for server in self.store.config.get('mcp_servers',[]):self.list.addItem(server['name']+('' if server['enabled'] else self.tr(' (disabled)')))

    def choose_working_directory(self):
        path=QFileDialog.getExistingDirectory(self,self.tr('Choose MCP working directory'),self.working_directory.text())
        if path:self.working_directory.setText(path)

    def new(self):
        self.list.setCurrentRow(-1);self.name.clear();self.transport.setCurrentIndex(0);self.command.clear();self.args.setPlainText('[]');self.working_directory.clear();self.env.setPlainText('{}');self.url.clear();self.token.clear();self.timeout.setValue(DEFAULT_TIMEOUT_SECONDS);self.enabled.setChecked(True)

    def load_row(self,index):
        if self.elicitation_dialog:
            self.close_elicitation()
            if self.remote:self.remote.stop('MCP input request cancelled; the request was not continued.')
        self.oauth_pending=None
        if self.oauth_authorization:
            authorization=self.oauth_authorization;self.oauth_authorization=None;authorization.stop()
        self.oauth_metadata=None;self.oauth_config=None;self.oauth_button.setText(self.tr('Sign in…'));self.oauth_button.setEnabled(False)
        if self.oauth_discovery:
            discovery=self.oauth_discovery;self.oauth_discovery=None;discovery.stop()
        self.oauth_challenge=None;self.oauth_challenge_url=None
        if self.process:self.finish_test(self.tr('Local MCP session closed.'))
        self.tool_details.clear();self.tool_choice.clear();self.tool_result.clear();self.discovered=None
        entries=self.store.config.get('mcp_servers',[])
        if 0<=index<len(entries):
            item=entries[index];remote=item.get('transport')=='http';self.name.setText(item['name']);self.transport.setCurrentIndex(1 if remote else 0);self.command.setText(item.get('command',''));self.args.setPlainText(json.dumps(item.get('args',[]),ensure_ascii=False));self.working_directory.setText(item.get('working_directory',''));self.env.setPlainText(json.dumps(item.get('env',{}),ensure_ascii=False));self.url.setText(item.get('url',''));self.token.clear();self.timeout.setValue(server_timeout(item));self.enabled.setChecked(item['enabled'])

    def form_matches(self,item):
        """Do not test a saved configuration while the editor shows different values."""
        remote=item.get('transport')=='http'
        if (self.name.text().strip()!=item['name'] or (self.transport.currentIndex()==1)!=remote or
                self.enabled.isChecked()!=item['enabled'] or self.timeout.value()!=server_timeout(item)):
            return False
        if remote:return self.url.text().strip()==item['url'] and not self.token.text()
        try:args=json.loads(self.args.toPlainText() or '[]');env=json.loads(self.env.toPlainText() or '{}')
        except (ValueError,RecursionError):return False
        return self.command.text().strip()==item['command'] and self.working_directory.text().strip()==item.get('working_directory','') and args==item['args'] and env==item.get('env',{})

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
                if credential and credential==old_id and prior.get('auth_type')=='oauth' and not token:item['auth_type']='oauth'
            else:
                try:args=json.loads(self.args.toPlainText() or '[]')
                except (ValueError,RecursionError):
                    QMessageBox.warning(self,self.tr('MCP servers'),self.tr('Arguments must be a valid JSON array. In Windows paths, use forward slashes or double each backslash.'));return
                try:env=json.loads(self.env.toPlainText() or '{}')
                except (ValueError,RecursionError):
                    QMessageBox.warning(self,self.tr('MCP servers'),self.tr('Environment names must be a valid JSON object.'));return
                item={'name':self.name.text().strip(),'command':self.command.text().strip(),'args':args,'enabled':self.enabled.isChecked()}
                if self.working_directory.text().strip():item['working_directory']=self.working_directory.text().strip()
                if env:item['env']=env
                elif not isinstance(env,dict):raise ValueError('Invalid MCP environment mappings')
            if self.timeout.value()!=DEFAULT_TIMEOUT_SECONDS or 'timeout_seconds' in prior:item['timeout_seconds']=self.timeout.value()
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
        if self.process or self.remote or self.oauth_discovery or self.oauth_authorization or self.oauth_pending:
            self.status.setText(self.tr('An MCP connection is already active. Close it or select another server before testing.'));return
        if not 0<=index<len(entries):
            self.status.setText(self.tr('Save and select a server before testing the connection.'));return
        item=entries[index]
        if not self.form_matches(item):self.status.setText(self.tr('Save your changes before testing this server.'));return
        if not item['enabled']:self.status.setText(self.tr('Enable and save this server before testing.'));return
        self.tool_details.clear();self.tool_choice.clear();self.tool_result.clear();self.discovered=None
        if item.get('transport')=='http':self.test_remote(item);return
        from .mcp_local import LocalSession
        try:self.process=LocalSession(item['command'],item['args'],self,env_refs=item.get('env',{}),timeout_seconds=server_timeout(item),working_directory=item.get('working_directory',''))
        except ValueError:self.status.setText(self.tr('The MCP environment or working directory is invalid on this system.'));return
        self.attach_elicitation(self.process,item['name'])
        self.discovered_config=dict(item)
        self.process.discovered.connect(self.local_discovered);self.process.called.connect(self.local_called);self.process.ended.connect(self.local_ended);self.process.shutdown_finished.connect(lambda result,config=dict(item):self.local_task_cleanup(result,config));self.process.shutdown_finished.connect(lambda _result,session=self.process:session.deleteLater())
        self.status.setText(self.tr('Connecting…'));self.process.start()

    def local_discovered(self,result):
        self.remote_done(result)
        self.status.setText(self.status.text()+self.tr(' · local session active'))

    def local_called(self,result):
        if 'error' in result:self.status.setText(result['error']);return
        self.show_call_result(result)

    def local_task_cleanup(self,result,config):
        if self._closed or self.discovered_config!=config or self.process is not None or not result.get('task_id'):return
        from .mcp_support import task_cleanup_text
        self.status.setText(task_cleanup_text({'server':config['name'],'task_id':result['task_id'],'task_cancelled':result.get('task_cancelled')}))

    def local_ended(self,result):
        self.close_elicitation()
        session=self.process;self.process=None;self.call_tool=None
        self.discovered=None;self.tool_choice.clear()
        self.status.setText(result['error']+(self.tr(' The call may have completed; inspect server state before retrying.') if result.get('call_uncertain') else ''))

    def finish_test(self,message):
        process=self.process
        if process is None:return
        self.close_elicitation();self.process=None;process.close();self.discovered=None;self.status.setText(message)

    def attach_elicitation(self,session,server):
        session.elicitation_enabled=True
        session.elicitation_requested.connect(lambda forms:self.show_elicitation(session,server,forms))

    def show_elicitation(self,session,server,forms):
        if self._closed or session not in (self.process,self.remote):return
        from .mcp_elicitation import ElicitationDialog
        retry_required=bool((getattr(session,'elicitation_pending',None) or {}).get('retry_required'));dialog=ElicitationDialog(server,forms,self,retry_required=retry_required);self.elicitation_dialog=dialog
        if hasattr(session,'elicitation_completed'):
            from .mcp_elicitation import track_opened
            dialog.url_opened.connect(lambda ident:track_opened(session,ident));session.elicitation_completed.connect(dialog.report_completion)
        def finished(code):
            if self.elicitation_dialog is not dialog:return
            self.elicitation_dialog=None;dialog.deleteLater()
            if self._closed or session not in (self.process,self.remote):return
            if code==QDialog.DialogCode.Accepted:
                if retry_required:session.continue_elicitation(dialog.responses,retry=dialog.retry_confirmed)
                else:session.continue_elicitation(dialog.responses)
            elif hasattr(session,'fail'):session.fail('MCP input request cancelled; the request was not continued.')
            else:session.stop('MCP input request cancelled; the request was not continued.')
        dialog.finished.connect(finished);dialog.open()

    def close_elicitation(self):
        dialog=self.elicitation_dialog;self.elicitation_dialog=None
        if dialog:dialog.blockSignals(True);dialog.reject();dialog.deleteLater()

    def done(self,result):
        self._closed=True;self.oauth_pending=None
        self.close_elicitation()
        if self.oauth_authorization:
            authorization=self.oauth_authorization;self.oauth_authorization=None;authorization.stop()
        if self.oauth_discovery:
            discovery=self.oauth_discovery;self.oauth_discovery=None;discovery.stop()
        if self.validation_job:self.validation_job.cancel.set()
        if self.process:self.finish_test(self.tr('Connection test cancelled.'))
        if self.remote:self.remote.stop()
        super().done(result)

    def discover_oauth(self):
        entries=self.store.config.get('mcp_servers',[]);index=self.list.currentRow()
        if self.oauth_discovery or self.oauth_authorization or self.oauth_pending or self.remote or self.process:self.status.setText(self.tr('An MCP connection is already active.'));return
        if not 0<=index<len(entries) or entries[index].get('transport')!='http':self.status.setText(self.tr('Save and select a remote server before discovering sign-in.'));return
        item=entries[index]
        if not self.form_matches(item):self.status.setText(self.tr('Save your changes before testing this server.'));return
        self.oauth_metadata=None;self.oauth_config=None;self.oauth_button.setEnabled(False)
        from .mcp_oauth_discovery import OAuthMetadataDiscovery
        challenge=self.oauth_challenge if self.oauth_challenge_url==item['url'] else None
        job=OAuthMetadataDiscovery(item['url'],challenge,self,timeout_ms=min(server_timeout(item)*1000,60000));self.oauth_discovery=job
        job.finished.connect(lambda result,job=job,config=dict(item):self.oauth_discovered(job,config,result))
        self.status.setText(self.tr('Discovering sign-in metadata…'));job.start()

    def oauth_discovered(self,job,config,result):
        if self.oauth_discovery is not job:return
        self.oauth_discovery=None;job.deleteLater()
        entries=self.store.config.get('mcp_servers',[]);index=self.list.currentRow()
        if self._closed or not 0<=index<len(entries) or entries[index]!=config or not self.form_matches(config):return
        if 'error' in result:self.status.setText(self.tr(result['error']));return
        server=result['authorization_server'];state=self.tr('supports PKCE') if server['pkce_s256'] else self.tr('does not advertise PKCE')
        if not server.get('public_client_supported',True):state=self.tr('does not support public clients')
        self.oauth_metadata=result;self.oauth_config=config;self.oauth_button.setEnabled(server['pkce_s256'] and server.get('public_client_supported',True))
        self.status.setText(self.tr('Authorization server: {issuer} · {state}.').format(issuer=server['issuer'],state=state))

    def sign_in_oauth(self):
        if self.oauth_authorization:
            job=self.oauth_authorization;self.oauth_authorization=None;job.stop();job.deleteLater();self.oauth_button.setText(self.tr('Sign in…'));self.oauth_button.setEnabled(True);self.status.setText(self.tr('OAuth sign-in cancelled.'));return
        if self.oauth_discovery or self.oauth_pending or self.remote or self.process:return
        config=self.oauth_config;metadata=self.oauth_metadata;entries=self.store.config.get('mcp_servers',[]);index=self.list.currentRow()
        if not config or not metadata or not 0<=index<len(entries) or entries[index]!=config or not self.form_matches(config):
            self.status.setText(self.tr('Save the server and discover sign-in again.'));return
        server=metadata['authorization_server']
        if not server.get('pkce_s256'):self.status.setText(self.tr('The authorization server does not support PKCE S256.'));return
        if not server.get('public_client_supported',True):self.status.setText(self.tr('The authorization server does not support public clients.'));return
        previous=''
        if config.get('auth_type')=='oauth':
            try:
                from .mcp_oauth_credentials import read_record
                import time
                saved=read_record(config['credential_id'],config['url'])
                if saved['issuer']==server['issuer'] and (saved.get('client_id_expires_at') is None or saved['client_id_expires_at']>time.time()):previous=saved['client_id']
            except Exception:pass
        if server.get('client_id_metadata_document_supported'):
            prompt=(self.tr('Enter a pre-registered public client ID or your hosted client metadata URL for {issuer}, or leave it blank to register automatically. The client must allow a loopback redirect on 127.0.0.1.') if server.get('registration_endpoint') else self.tr('Enter a pre-registered public client ID or your hosted client metadata URL for {issuer}. The client must allow a loopback redirect on 127.0.0.1.')).format(issuer=server['issuer'])
        else:
            prompt=(self.tr('Enter a pre-registered public client ID for {issuer}, or leave it blank to register automatically. The client must allow a loopback redirect on 127.0.0.1.') if server.get('registration_endpoint') else self.tr('Enter a pre-registered public client ID for {issuer}. The client must allow a loopback redirect on 127.0.0.1.')).format(issuer=server['issuer'])
        client_id,accepted=QInputDialog.getText(self,self.tr('OAuth sign-in'),prompt,QLineEdit.EchoMode.Normal,previous)
        if not accepted:return
        client_id=client_id.strip()
        if not client_id and not server.get('registration_endpoint'):self.status.setText(self.tr('An OAuth client ID is required.'));return
        current=self.store.config.get('mcp_servers',[])
        if self._closed or self.oauth_metadata is not metadata or self.oauth_config!=config or self.list.currentRow()!=index or not 0<=index<len(current) or current[index]!=config or not self.form_matches(config):return
        challenge=self.oauth_challenge if self.oauth_challenge_url==config['url'] else None
        scopes=challenge['scope'] if challenge is not None and 'scope' in challenge else ' '.join(metadata['resource']['scopes_supported'])
        from .mcp_oauth_flow import OAuthAuthorization
        job=OAuthAuthorization(config['url'],server,client_id,scopes,self,timeout_ms=max(180000,server_timeout(config)*1000));self.oauth_authorization=job;self.oauth_button.setText(self.tr('Cancel sign-in'));self.oauth_button.setEnabled(True)
        job.finished.connect(lambda result,job=job,config=dict(config),server=dict(server),client_id=client_id:self.oauth_signed_in(job,config,server,client_id,result))
        self.status.setText(self.tr('Registering the client and opening your browser…') if not client_id else self.tr('Complete sign-in in your browser…'));job.start()

    def oauth_signed_in(self,job,config,server,client_id,result):
        if self.oauth_authorization is not job:return
        self.oauth_authorization=None;job.deleteLater();entries=list(self.store.config.get('mcp_servers',[]));index=self.list.currentRow()
        if self._closed:return
        self.oauth_button.setText(self.tr('Sign in…'))
        if not 0<=index<len(entries) or entries[index]!=config or not self.form_matches(config):self.oauth_button.setEnabled(False);return
        if 'error' in result:self.oauth_button.setEnabled(True);self.status.setText(self.tr(result['error']));return
        from .mcp_oauth_credentials import make_record,write_record
        new_id=uuid.uuid4().hex;old_id=config.get('credential_id','');new_written=False
        try:
            record=make_record(config['url'],server['issuer'],server['token_endpoint'],result.get('client_id',client_id),result,client_id_expires_at=result.get('client_id_expires_at'))
            replacement=dict(config,credential_id=new_id,auth_type='oauth');updated=list(entries);updated[index]=replacement;validate_servers(updated)
            write_record(new_id,record);new_written=True
            if self._closed or self.oauth_config!=config or not self.oauth_metadata or self.oauth_metadata.get('authorization_server')!=server or self.list.currentRow()!=index or self.store.config.get('mcp_servers',[])!=entries or entries[index]!=config or not self.form_matches(config):raise ValueError('MCP server changed during sign-in')
            self.store.config['mcp_servers']=updated
            try:self.store.flush()
            except Exception:
                if self.store.config.get('mcp_servers') is updated:self.store.config['mcp_servers']=entries
                raise
        except Exception:
            if new_written:
                try:
                    import keyring
                    keyring.delete_password('Agentnik',new_id)
                except Exception:pass
            if not self._closed and self.oauth_config==config:
                self.oauth_button.setEnabled(True);self.status.setText(self.tr('Could not save the OAuth credential. Check the server settings and credential store.'))
            return
        if old_id and old_id!=new_id:
            try:
                import keyring
                keyring.delete_password('Agentnik',old_id)
            except Exception:pass
        self.populate();self.list.setCurrentRow(index);self.status.setText(self.tr('OAuth sign-in saved. Test the connection.'))

    def test_remote(self,item):
        self.oauth_challenge=None;self.oauth_challenge_url=None
        if item.get('auth_type')=='oauth':
            self.resolve_oauth(item,lambda token:self.start_remote_test(item,token));return
        token=''
        if item.get('credential_id'):
            try:
                import keyring
                token=keyring.get_password('Agentnik',item['credential_id']) or ''
            except Exception:token=''
            if not token:self.status.setText(self.tr('MCP credential is unavailable in the credential store.'));return
            if len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token):self.status.setText(self.tr('MCP credential has an invalid format.'));return
        self.start_remote_test(item,token)

    def resolve_oauth(self,item,callback):
        from .mcp_oauth_credentials import oauth_credential_broker
        ticket=object();self.oauth_pending=ticket;self.status.setText(self.tr('Checking OAuth credential…'))
        def completed(result):
            if self._closed or self.oauth_pending is not ticket:return
            self.oauth_pending=None;entries=self.store.config.get('mcp_servers',[]);index=self.list.currentRow()
            if not 0<=index<len(entries) or entries[index]!=item or not self.form_matches(item):return
            if 'error' in result:self.status.setText(self.tr(result['error']));return
            callback(result['token'])
        oauth_credential_broker().request(item,completed,lambda:item in self.store.config.get('mcp_servers',[]))

    def start_remote_test(self,item,token):
        from .mcp_remote import RemoteProbe
        self.discovered_config=dict(item);self.remote=RemoteProbe(item['url'],token,self,timeout_seconds=server_timeout(item));self.remote.finished.connect(self.remote_done);self.status.setText(self.tr('Connecting…'));self.remote.start()

    def remote_done(self,result):
        probe=self.remote;self.remote=None
        if probe and getattr(probe,'oauth_challenge',None) is not None and self.discovered_config:
            self.oauth_challenge=probe.oauth_challenge;self.oauth_challenge_url=self.discovered_config.get('url')
        if probe:probe.deleteLater()
        if 'error' in result:self.status.setText(result['error']+(self.tr(' Session close not confirmed.') if result.get('session_closed') is False else ''));return
        self.discovered={'config':self.discovered_config,'tools':result.get('tool_details',[]),'task_capabilities':result.get('task_capabilities',{})}
        self.tool_choice.clear();self.tool_choice.addItems([item['name'] for item in self.discovered['tools']])
        self.status.setText(self.tr('Connected: {name} {version} · MCP {protocol} · tools: {tools}').format(name=result['name'],version=result['version'],protocol=result['protocol'],tools=', '.join(result.get('tools',[])) or self.tr('none'))+(self.tr(' (more available)') if result.get('more_tools') else '')+(self.tr(' · session close not confirmed') if result.get('session_closed') is False else ''))
        sections=[]
        task_caps=result.get('task_capabilities',{})
        if 'tasks' in result.get('capabilities',[]):
            sections.append(self.tr('Server task capabilities (experimental): ')+json.dumps(task_caps,ensure_ascii=True))
        for detail in result.get('tool_details',[]):
            description=detail['description'] or self.tr('(no description)')
            if detail['description_clipped']:description+='\n'+self.tr('[Description truncated or unavailable]')
            schema=json.dumps(detail['schema'],ensure_ascii=True,indent=2) if detail['schema_status']=='available' else self.tr('[Input schema {status}]').format(status=detail['schema_status'])
            hints=('\n'+self.tr('Server-supplied hints (untrusted): ')+json.dumps(detail['annotations'],ensure_ascii=True) if detail.get('annotations') else '')
            output=('\n'+self.tr('Output schema:')+'\n'+(json.dumps(detail['output_schema'],ensure_ascii=True,indent=2) if detail.get('output_schema_status')=='available' else self.tr('[Output schema unavailable]'))) if 'output_schema_status' in detail else ''
            sections.append(detail['name']+'\n'+description+hints+'\n'+self.tr('Task execution: ')+detail.get('task_support','forbidden')+'\n'+self.tr('Input schema:')+'\n'+schema+output)
        self.tool_details.setPlainText('\n\n'.join(sections))

    def call_remote(self):
        if self.remote or self.oauth_pending or self.validation_job or not self.discovered:return
        index=self.list.currentRow();entries=self.store.config.get('mcp_servers',[])
        if not 0<=index<len(entries) or entries[index]!=self.discovered['config']:
            self.status.setText(self.tr('Server configuration changed. Test it again.'));return
        item=entries[index];tool=next((tool for tool in self.discovered['tools'] if tool['name']==self.tool_choice.currentText()),None)
        if not tool or tool['schema_status']!='available' or tool['description_clipped'] or tool.get('output_schema_status','available')!='available':self.status.setText(self.tr('This tool has incomplete metadata and cannot be called.'));return
        if tool.get('task_support')=='required' and not self.discovered['task_capabilities'].get('tool_calls'):self.status.setText(self.tr('This tool requires MCP task execution on a capable server.'));return
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
        if item.get('auth_type')=='oauth':
            self.resolve_oauth(item,lambda token:self.validated_call_with_token(index,item,tool,args,raw,token));return
        token=''
        if item.get('credential_id'):
            try:
                import keyring
                token=keyring.get_password('Agentnik',item['credential_id']) or ''
            except Exception:token=''
            if not token or len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token):self.status.setText(self.tr('MCP credential is unavailable or invalid.'));return
        self.validated_call_with_token(index,item,tool,args,raw,token)

    def validated_call_with_token(self,index,item,tool,args,raw,token):
        if self._closed:return
        if token and token in json.dumps(args,ensure_ascii=False):self.status.setText(self.tr('Arguments contain the configured credential.'));return
        if self.list.currentRow()!=index or self.tool_choice.currentText()!=tool['name'] or self.tool_args.toPlainText()!=raw:self.status.setText(self.tr('Server, tool, or arguments changed. Review and try again.'));return
        entries=self.store.config.get('mcp_servers',[])
        if not 0<=index<len(entries):self.status.setText(self.tr('Server configuration changed. Test it again.'));return
        if self.list.currentRow()!=index or self.store.config.get('mcp_servers',[])!=entries or self.discovered is None or entries[index]!=self.discovered['config']:
            self.status.setText(self.tr('Server configuration changed. Test it again.'));return
        self.call_tool=dict(tool)
        if item.get('transport')!='http':
            if not self.process or not self.process.call(tool,args):self.status.setText(self.tr('Local MCP session is no longer available.'));return
            self.tool_result.clear();self.status.setText(self.tr('Calling tool…'));return
        from .mcp_remote import RemoteProbe
        self.tool_result.clear();self.remote=RemoteProbe(item['url'],token,self,invocation={'tool':tool,'arguments':args},timeout_seconds=server_timeout(item));self.attach_elicitation(self.remote,item['name']);self.remote.finished.connect(self.call_done);self.status.setText(self.tr('Calling tool…'));self.remote.start()

    def call_done(self,result):
        self.close_elicitation()
        probe=self.remote;self.remote=None
        if probe:probe.deleteLater()
        if 'error' in result:
            self.call_tool=None
            message=result['error']+(self.tr(' The call may have reached the server; inspect its state before retrying.') if result.get('call_uncertain') else '')+(self.tr(' Session close not confirmed.') if result.get('session_closed') is False else '')
            if result.get('task_id'):
                from .mcp_support import task_cleanup_text
                message+=' '+task_cleanup_text({'server':self.discovered_config['name'],'task_id':result['task_id'],'task_cancelled':result.get('task_cancelled')})
            self.status.setText(message);return
        self.show_call_result(result)

    def show_call_result(self,result):
        tool=self.call_tool or {};self.call_tool=None
        def display(valid):
            self.validation_job=None
            if self._closed:return
            outcome=result.get('call_result',{})
            self.tool_result.setPlainText(json.dumps(outcome,ensure_ascii=True,indent=2))
            message=(self.tr('Tool returned an error.') if outcome.get('isError') else self.tr('Tool call completed.')) if valid else self.tr('Structured output failed validation; the tool may have completed. Inspect server state before retrying.')
            self.status.setText(message+(self.tr(' Session close not confirmed.') if result.get('session_closed') is False else ''))
        if 'output_schema_status' not in tool:display(True);return
        from .mcp_schema import validate_tool_result
        from .ui import Job
        self.status.setText(self.tr('Validating tool output…'))
        def work(progress,cancel):
            if cancel.is_set():return False
            try:return validate_tool_result(tool,result.get('call_result'))
            except ValueError:return False
        self.validation_job=Job(work,display,self.validation_failed)

"""Repository picker and Agentnik-owned coding pane."""
from pathlib import Path
import json
import re
import threading
from urllib.parse import urlsplit
from PySide6.QtCore import Qt,Signal,QObject,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication,QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QPushButton,QDialogButtonBox,QFileDialog,QInputDialog,QMessageBox,QPlainTextEdit,QComboBox,QCheckBox,QSpinBox
from .repositories import RepositoryRegistry
from .coding import SimulationRun,plain
from .code_agent import CodingRun
from .research import scrub
from . import decision_advice
from .decision_advice import parse_advice
from .code_limits import FIELDS,coding_limits
from .web import public_url
from . import core,routing
from .research_ui import SearchBackends


class RepositoryPicker(QDialog):
    def __init__(self,parent,registry,select=True):
        super().__init__(parent);self.registry=registry;self.selected_id=None;self.select=select
        self.setWindowTitle(self.tr('Choose repository') if select else self.tr('Repositories'));self.resize(680,400)
        layout=QVBoxLayout(self);self.search=QLineEdit();self.search.setPlaceholderText(self.tr('Search project names and paths'));layout.addWidget(self.search)
        self.items=QListWidget();layout.addWidget(self.items);self.search.textChanged.connect(self.refresh)
        actions=QHBoxLayout();layout.addLayout(actions)
        for label,fn in [(self.tr('Add folder'),self.add),(self.tr('Rename'),self.rename),(self.tr('Locate folder'),self.locate),(self.tr('Remove from list'),self.remove)]:
            button=QPushButton(label);button.clicked.connect(fn);actions.addWidget(button)
        self.hint=QLabel(self.tr('Git is optional. Removing an entry never deletes files. Add a folder to begin.'));self.hint.setWordWrap(True);layout.addWidget(self.hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Open|QDialogButtonBox.StandardButton.Cancel if select else QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.choose);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        if select:self.items.itemDoubleClicked.connect(lambda *_:self.choose())
        self.refresh()

    def selected(self):
        item=self.items.currentItem();return self.registry.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def refresh(self,*_):
        old=self.selected();self.items.clear();needle=self.search.text().casefold()
        for row in self.registry.list():
            if needle not in (row['name']+' '+row['path']).casefold():continue
            item=QListWidgetItem(row['name']+(' · '+self.tr('missing/unavailable') if not row['available'] else '')+'\n'+row['path']);item.setData(Qt.ItemDataRole.UserRole,row['id']);self.items.addItem(item)
            if old and row['id']==old['id']:self.items.setCurrentItem(item)
        if self.items.currentRow()<0 and self.items.count():self.items.setCurrentRow(0)

    def attempt(self,fn):
        try:fn();self.refresh()
        except (OSError,ValueError) as exc:QMessageBox.warning(self,self.tr('Repositories'),str(exc))

    def add(self):
        path=QFileDialog.getExistingDirectory(self,self.tr('Add project folder'))
        if path:self.attempt(lambda:self.registry.put(path))

    def rename(self):
        row=self.selected()
        if not row:return
        name,ok=QInputDialog.getText(self,self.tr('Rename project'),self.tr('Name:'),text=row['name'])
        if ok:self.attempt(lambda:self.registry.rename(row['id'],name))

    def locate(self):
        row=self.selected()
        if not row:return
        path=QFileDialog.getExistingDirectory(self,self.tr('Locate project folder'))
        if path:self.attempt(lambda:self.registry.put(path,row['name'],row['id']))

    def remove(self):
        row=self.selected()
        if row and QMessageBox.question(self,self.tr('Remove project'),self.tr('Remove this entry from the list? Its files and history will remain.'))==QMessageBox.StandardButton.Yes:
            self.attempt(lambda:self.registry.remove(row['id']))

    def choose(self):
        row=self.selected()
        if not row:return
        try:self.registry.directory(row['path'])
        except (OSError,ValueError) as exc:QMessageBox.warning(self,self.tr('Unavailable project'),str(exc));return
        self.selected_id=row['id'];self.accept()


class CodeEvents(QObject):
    event=Signal(object)


class CodingLimitsDialog(QDialog):
    def __init__(self,parent,values):
        super().__init__(parent);self.setWindowTitle(self.tr('Coding run limits'))
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form);self.fields={}
        labels={'rounds':self.tr('Tool rounds'),'requests':self.tr('Model requests'),'calls':self.tr('Tool calls'),'turn_seconds':self.tr('Time (seconds)'),'context_bytes':self.tr('Retained context (bytes)')}
        for key,(_,minimum,maximum) in FIELDS.items():
            box=QSpinBox();box.setRange(minimum,maximum);box.setValue(values[key]);form.addRow(labels[key],box);self.fields[key]=box
        hint=QLabel(self.tr('Limits are shared by Heavy, Light, and web research for each run.'));hint.setWordWrap(True);layout.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.reset);layout.addWidget(buttons)

    def reset(self):
        for key,value in coding_limits().items():self.fields[key].setValue(value)

    def values(self):return coding_limits({key:box.value() for key,box in self.fields.items()})


class CodingSourcesDialog(QDialog):
    def __init__(self,parent,sources):
        super().__init__(parent);self.setWindowTitle(self.tr('Research sources'));self.resize(680,380)
        layout=QVBoxLayout(self);hint=QLabel(self.tr('Sources from the most recent coding run. Review each source before relying on it.'));hint.setWordWrap(True);layout.addWidget(hint)
        self.items=QListWidget();layout.addWidget(self.items)
        for source in sources:
            try:url=public_url(source['url'])
            except (KeyError,ValueError):continue
            item=QListWidgetItem(source['id']+' · '+source['title']+'\n'+url);item.setData(Qt.ItemDataRole.UserRole,url);item.setToolTip(url);self.items.addItem(item)
        row=QHBoxLayout();layout.addLayout(row)
        open_button=QPushButton(self.tr('Open in browser'));open_button.clicked.connect(self.open_source);row.addWidget(open_button)
        copy_button=QPushButton(self.tr('Copy link'));copy_button.clicked.connect(self.copy_source);row.addWidget(copy_button)
        close_button=QPushButton(self.tr('Close'));close_button.clicked.connect(self.accept);row.addWidget(close_button)
        if self.items.count():self.items.setCurrentRow(0)

    def selected_url(self):
        item=self.items.currentItem()
        if not item:return None
        try:return public_url(item.data(Qt.ItemDataRole.UserRole))
        except ValueError:return None

    def open_source(self):
        url=self.selected_url()
        if url:QDesktopServices.openUrl(QUrl(url))

    def copy_source(self):
        url=self.selected_url()
        if url:QApplication.clipboard().setText(url)


class CodeTab(QWidget):
    updated=Signal()
    def __init__(self,window,session):
        super().__init__();self.window=window;self.store=window.store;self.session=session;self.job=None;self.model_jobs={};self._closed=False;self.run_id=None;self.pending_fingerprint=None;self.advice_fingerprint=None;self.advice_job=None;self.advice_connection=None;self.advice_destination=''
        self.events=CodeEvents(self);self.events.event.connect(self.receive)
        if session.get("code_state") in ("running","awaiting_approval"):
            session["code_state"]="interrupted"
            session.setdefault("code_activity",[]).append({"kind":"interrupted","text":"Interrupted coding run; nothing resumes automatically."})
            session["code_activity"]=session["code_activity"][-32:]
            self.store.save(session)
        layout=QVBoxLayout(self)
        header=QHBoxLayout();layout.addLayout(header)
        title=QLabel(session['project_name']);title.setTextFormat(Qt.TextFormat.PlainText);header.addWidget(title)
        path=QLabel(self.tr('Working directory snapshot: {path}').format(path=session['path_snapshot']));path.setTextFormat(Qt.TextFormat.PlainText);path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);path.setToolTip(session['path_snapshot']);header.addWidget(path,1)
        current=window.repositories.get(session['project_id'])
        note=''
        if not Path(session['path_snapshot']).is_dir():note+=' '+self.tr('The saved folder is missing or unavailable.')
        if current is None:note+=' '+self.tr('This project was removed from the registry; its history is retained.')
        elif current['path']!=session['path_snapshot']:note+=' '+self.tr('The registered folder moved. This session retains its original path; open a new Code pane to use the relocated folder.')
        if note:
            warning=QLabel(note.strip());warning.setWordWrap(True);warning.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(warning)
        self.activity=QPlainTextEdit('\n'.join(self.activity_text(e) for e in session.get('code_activity',[])) or self.tr('No commands have been run.'));self.activity.setReadOnly(True);layout.addWidget(self.activity,1)
        self.composer=QPlainTextEdit(session.get('draft',''));self.composer.setPlaceholderText(self.tr('Describe the coding task; repository files may be sent to the selected models'));self.composer.setMaximumHeight(90);layout.addWidget(self.composer)
        context=session.get('coding_context')
        self.context_view=QPlainTextEdit(self.context_text(context))
        self.context_view.setReadOnly(True);self.context_view.setMaximumHeight(110);layout.addWidget(self.context_view)
        self.use_context=QCheckBox(self.tr('Send previous task and answer with next run (up to 2,048 characters each)'));self.use_context.setEnabled(bool(context))
        options=QHBoxLayout();layout.addLayout(options)
        self.roles={}
        bindings=dict(session.get('coding_models',{}));bindings['decision']=session.get('coding_decision_model',{})
        self.model_toggle=QPushButton(self.tr('Models'));self.model_toggle.setCheckable(True);layout.addWidget(self.model_toggle)
        self.model_panel=QWidget();model_layout=QVBoxLayout(self.model_panel);layout.addWidget(self.model_panel);self.model_panel.hide()
        self.model_toggle.toggled.connect(self.model_panel.setVisible)
        for role in ('heavy','light','decision'):
            row=QHBoxLayout();model_layout.addLayout(row);row.addWidget(QLabel({'heavy':self.tr('Heavy model'),'light':self.tr('Light model'),'decision':self.tr('Decision model')}[role]))
            connection=QComboBox();connection.addItem(self.tr('Not configured'),'');
            for name in window.connections:connection.addItem(name,name)
            model=QLineEdit();model.setPlaceholderText(self.tr('Model alias (any supported coding model)'))
            saved=bindings.get(role,{})
            missing=saved.get('connection','')
            if missing and connection.findData(missing)<0:connection.addItem(missing+' (unavailable)',missing)
            connection.setCurrentIndex(max(0,connection.findData(saved.get('connection',''))));model.setText(saved.get('model',''))
            row.addWidget(connection);row.addWidget(model,1);self.roles[role]=(connection,model)
            choose=QPushButton(self.tr('Choose model…'));choose.clicked.connect(lambda _,r=role:self.choose_model(r));row.addWidget(choose)
            connection.currentIndexChanged.connect(lambda _,r=role:self.role_changed(r))
            model.editingFinished.connect(self.save_models)
        self.advice_enabled=QCheckBox(self.tr('Check shell approvals with Decision model'))
        self.advice_enabled.setChecked(session.get('coding_advice_enabled',False));self.advice_enabled.toggled.connect(self.save_advice_enabled);model_layout.addWidget(self.advice_enabled)
        disclosure=QLabel(self.tr('When enabled, each shell proposal sends its command, working directory, shell, and environment variable names to the selected Decision endpoint. Environment values are not sent. Advice never approves a command.'))
        disclosure.setWordWrap(True);model_layout.addWidget(disclosure)
        self.light_enabled=QCheckBox(self.tr('Allow Light model delegation'));self.light_enabled.setChecked(session.get('coding_light_enabled',True) is not False);options.addWidget(self.light_enabled);options.addWidget(self.use_context)
        self.light_enabled.toggled.connect(self.save_light_enabled)
        self.web_enabled=QCheckBox(self.tr('Allow web research'));self.web_enabled.setToolTip(self.tr('Search queries go to Google or direct Ollama Cloud; pages are read from public websites.'))
        self.web_enabled.setChecked(session.get('coding_web_enabled',False));options.addWidget(self.web_enabled)
        self.web_enabled.toggled.connect(self.save_web_enabled)
        self.limits_button=QPushButton(self.tr('Limits…'));self.limits_button.clicked.connect(self.configure_limits);options.addWidget(self.limits_button)
        self.sources_button=QPushButton();self.sources_button.clicked.connect(self.show_sources)
        run_row=QHBoxLayout();layout.addLayout(run_row)
        self.send=QPushButton(self.tr('Run'));self.send.clicked.connect(self.start_coding);run_row.addWidget(self.send)
        self.simulate=QPushButton(self.tr('Simulate'));self.simulate.clicked.connect(self.start_simulation);run_row.addWidget(self.simulate)
        self.cancel_button=QPushButton(self.tr('Cancel'));self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel);run_row.addWidget(self.cancel_button)
        run_row.addWidget(self.model_toggle)
        self.search_settings=QPushButton(self.tr('Search settings…'));self.search_settings.setToolTip(self.tr('Manage search profiles shared with Chat'));self.search_settings.clicked.connect(self.configure_search);run_row.addWidget(self.search_settings)
        run_row.addWidget(self.sources_button);self.update_sources_button()
        self.approval_panel=QWidget();review=QVBoxLayout(self.approval_panel);layout.addWidget(self.approval_panel);self.approval_panel.hide()
        self.approval=QPlainTextEdit();self.approval.setReadOnly(True);self.approval.setPlaceholderText(self.tr('Command approval preview'));review.addWidget(self.approval)
        self.advice_label=QLabel();self.advice_label.setWordWrap(True);self.advice_label.setTextFormat(Qt.TextFormat.PlainText);review.addWidget(self.advice_label);self.advice_label.hide()
        actions=QHBoxLayout();review.addLayout(actions)
        self.approve=QPushButton(self.tr('Approve proposed step'));self.reject=QPushButton(self.tr('Reject proposed step'))
        for button in (self.approve,self.reject):actions.addWidget(button);button.setEnabled(False)
        self.approve.clicked.connect(lambda:self.decide(True));self.reject.clicked.connect(lambda:self.decide(False))
        self.diff=QPlainTextEdit();self.diff.setReadOnly(True);self.diff.setPlaceholderText(self.tr('Review the complete proposed file diff before approving'));review.addWidget(self.diff)
        self.composer.textChanged.connect(self.save_draft)

    def choose_model(self,role):
        if self.job or role in self.model_jobs:return
        name=self.roles[role][0].currentData()
        if not name:return QMessageBox.information(self,self.tr('Coding model'),self.tr('Choose a connection first, or enter an alias manually.'))
        c=dict(self.window.connections.get(name,{}))
        from .ui import Job
        def done(names):
            self.model_jobs.pop(role,None)
            if self._closed or self.job or self.roles[role][0].currentData()!=name:return
            choices=[value for value in names if isinstance(value,str) and len(value)<=512][:2000]
            title={'heavy':self.tr('Choose Heavy model'),'light':self.tr('Choose Light model'),'decision':self.tr('Choose Decision model')}[role]
            model,ok=QInputDialog.getItem(self,title,self.tr('Model alias:'),choices,0,True)
            if ok:self.roles[role][1].setText(model);self.save_models()
        def failed(_):
            self.model_jobs.pop(role,None)
            if not self._closed:QMessageBox.warning(self,self.tr('Coding models'),self.tr('Model listing failed. You can enter an alias manually.'))
        self.model_jobs[role]=Job(lambda *_:core.models(c),done,failed)

    def context_text(self,context):
        if not context:return self.tr('No completed coding task available.')
        return self.tr('Previous task:\n{task}\n\nPrevious answer:\n{answer}').format(task=context['task'],answer=context['answer'])

    def role_changed(self,role):
        connection,model=self.roles[role];c=self.window.connections.get(connection.currentData(),{})
        model.setText(c.get('model',''));self.save_models()

    def save_models(self):
        self.session['coding_models']={role:{'connection':self.roles[role][0].currentData(),'model':self.roles[role][1].text().strip()} for role in ('heavy','light')}
        widgets=self.roles['decision'];self.session['coding_decision_model']={'connection':widgets[0].currentData(),'model':widgets[1].text().strip()}
        self.store.save(self.session)

    def save_light_enabled(self,enabled):
        self.session['coding_light_enabled']=enabled;self.store.save(self.session)

    def save_web_enabled(self,enabled):
        self.session['coding_web_enabled']=enabled;self.store.save(self.session)

    def save_advice_enabled(self,enabled):
        self.session['coding_advice_enabled']=enabled;self.store.save(self.session)

    def configure_limits(self):
        if self.job:return
        dialog=CodingLimitsDialog(self,coding_limits(self.session.get('coding_limits')))
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.session['coding_limits']=dialog.values();self.store.save(self.session)

    def configure_search(self):
        if not self.job:SearchBackends(self,self.store).exec()

    def update_sources_button(self):
        count=len(self.session.get('coding_sources',[]));self.sources_button.setText(self.tr('Sources ({count})').format(count=count));self.sources_button.setVisible(count>0)

    def show_sources(self):
        CodingSourcesDialog(self,self.session.get('coding_sources',[])).exec()

    def show_advice(self,raw=None,fingerprint=None):
        if raw is None:
            self.advice_label.setText(self.tr('Safety advice: NOT CHECKED · No System One request was made.'))
        else:
            if not self.job or not self.pending_fingerprint or fingerprint!=self.pending_fingerprint or fingerprint!=self.advice_fingerprint:return
            result=parse_advice(raw);category=result['category']
            labels={'safe':self.tr('SAFE'),'warning':self.tr('WARNING'),'risky':self.tr('RISKY'),'privacy':self.tr('PRIVACY'),'danger':self.tr('DANGER'),'unknown':self.tr('UNKNOWN')}
            guides={'safe':self.tr('Low apparent risk; review before approving.'),'warning':self.tr('Uncertain or requires closer review.'),'risky':self.tr('May change files or system state.'),'privacy':self.tr('May expose private information.'),'danger':self.tr('May cause severe or irreversible effects.'),'unknown':self.tr('No valid category was returned.')}
            confidence=result['confidence']
            detail=self.tr('Confidence unavailable') if confidence is None else self.tr('Confidence: {value}').format(value=f'{confidence:.0%}')
            self.advice_label.setText(self.tr('Safety advice: {label} · {detail}\nCategory guide: {guide}\nAdvisory only; you decide.').format(label=labels[category],detail=detail,guide=guides[category]))
        self.advice_label.show()

    def check_advice(self,proposal,fingerprint):
        if not self.advice_connection:return
        from .ui import Job
        from shiboken6 import isValid
        connection=dict(self.advice_connection);run_id=self.run_id
        self.approve.setEnabled(False);self.reject.setEnabled(False)
        self.advice_label.setText(self.tr('Checking safety advice with {destination}…').format(destination=self.advice_destination))
        secret=connection.get('api_key','')
        fields=[str(proposal.get(key,'')) for key in ('command','cwd','shell','environment_keys')]
        if any('[redacted]' in value or (secret and secret in value) for value in fields):
            self.advice_label.setText(self.tr('Safety advice: UNKNOWN · The proposal contains a configured credential; no request was made.'))
            self.approve.setEnabled(True);self.reject.setEnabled(True);return
        def active():
            return isValid(self) and not self._closed and self.job is not None and self.run_id==run_id and self.pending_fingerprint==fingerprint and self.advice_fingerprint==fingerprint
        def done(raw):
            if not active():return
            self.advice_job=None;self.show_advice(raw,fingerprint);self.advice_label.setText(self.advice_label.text()+'\n'+self.tr('Decision endpoint: {destination}').format(destination=self.advice_destination));self.approve.setEnabled(True);self.reject.setEnabled(True)
            result=parse_advice(raw);confidence=(' confidence '+f'{result["confidence"]:.0%}') if result['confidence'] is not None else ' confidence unavailable'
            self.record('advice','System One advice '+result['category'].upper()+confidence+' for proposal '+fingerprint[:12]+' via '+self.advice_destination)
        def failed(_):
            if not active():return
            self.advice_job=None;self.advice_label.setText(self.tr('Safety advice: UNKNOWN · The decision check failed or timed out. Review the command yourself.')+'\n'+self.tr('Decision endpoint: {destination}').format(destination=self.advice_destination))
            self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('advice','System One advice unavailable for proposal '+fingerprint[:12]+' via '+self.advice_destination)
        self.advice_job=Job(lambda emit,cancel:decision_advice.request(connection,proposal,cancel),done,failed)

    def role_connection(self,role):
        name=self.roles[role][0].currentData()
        if not name:return None
        c=dict(self.window.connections.get(name,{}));c['model']=self.roles[role][1].text().strip()
        if not c.get('url') or not c.get('model'):
            raise ValueError({'heavy':self.tr('Choose a connection and model alias for Heavy.'),'light':self.tr('Choose a connection and model alias for Light.'),'decision':self.tr('Choose a connection and model alias for Decision.')}[role])
        return c

    def start_coding(self):
        if self.job or self._closed:return
        try:
            self.save_models();heavy=self.role_connection('heavy');light=self.role_connection('light') if self.light_enabled.isChecked() else None
            advice=self.role_connection('decision') if self.advice_enabled.isChecked() else None
            if self.advice_enabled.isChecked() and not advice:raise ValueError(self.tr('Choose a Decision model before enabling safety advice.'))
            destination=(self.roles['decision'][0].currentText()+' / '+advice['model']+' / '+core.endpoint(advice,'decision')) if advice else ''
            if not heavy or not self.composer.toPlainText().strip():raise ValueError(self.tr('Choose a heavy model and enter a coding task'))
            context=self.session.get('coding_context') if self.use_context.isChecked() else None
            enabled=self.web_enabled.isChecked();backends=[];provider='none'
            if enabled:
                strict=routing.connection_defaults(self.store.config,self.roles['heavy'][0].currentData(),heavy)['access_policy']=='strict_public'
                parsed=urlsplit(heavy['url']);direct=parsed.scheme=='https' and parsed.hostname=='ollama.com' and parsed.port in (None,443)
                if not strict:
                    backends=self.store.web_backend_specs() if direct else []
                    provider='ollama' if any(b.get('kind')=='ollama' and b.get('key') for b in backends) else 'google'
            run=CodingRun(heavy,self.session['path_snapshot'],self.composer.toPlainText(),light,context,backends,limits=self.session.get('coding_limits'),web_enabled=enabled,search_provider=provider)
        except ValueError as exc:QMessageBox.warning(self,self.tr('Coding settings'),str(exc));return
        self.advice_connection=advice;self.advice_destination=destination
        self.launch(run,'Agentnik coding started. Repository content goes to the selected models; edits await approval.')
        if enabled:self.record('output',{'none':'Web research: public page reads only; strict navigation disables search.','google':'Web research: Google search and public page reads.','ollama':'Web research: Ollama search and public page reads.'}[provider])

    def launch(self,run,notice):
        if isinstance(run,CodingRun):self.session['coding_sources']=[];self.update_sources_button()
        self.job=run;self.run_id=run.run_id;self.pending_fingerprint=None;self.session['code_state']='running'
        self.simulate.setEnabled(False);self.send.setEnabled(False);self.cancel_button.setEnabled(True)
        self.light_enabled.setEnabled(False);self.web_enabled.setEnabled(False);self.limits_button.setEnabled(False);self.search_settings.setEnabled(False);self.advice_enabled.setEnabled(False)
        self.use_context.setEnabled(False)
        for connection,model in self.roles.values():connection.setEnabled(False);model.setEnabled(False)
        self.diff.clear();self.approval.clear();self.record('started',notice)
        signals=self.events
        def work():
            try:run.run(signals.event.emit)
            except RuntimeError:pass
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def save_draft(self):
        self.session['draft']=self.composer.toPlainText();self.store.save(self.session);self.updated.emit()

    def activity_text(self,event):
        kind=event.get('kind','');text=plain(event.get('text',kind))
        fixed={('started','Agentnik coding started. Repository content goes to the selected models; edits await approval.'):self.tr('Agentnik coding started. Repository content goes to the selected models; edits await approval.'),
               ('started','Simulation started; no commands or inference will run.'):self.tr('Simulation started; no commands or inference will run.'),
               ('approval','Awaiting explicit approval for simulated step.'):self.tr('Awaiting explicit approval for simulated step.'),
               ('cancelled','Run cancelled. No further tool work will be scheduled; already approved edits are retained.'):self.tr('Run cancelled. No further tool work will be scheduled; already approved edits are retained.'),
               ('interrupted','Interrupted coding run; nothing resumes automatically.'):self.tr('Interrupted coding run; nothing resumes automatically.')}
        if (kind,text) in fixed:return fixed[(kind,text)]
        prefix='Awaiting approval for file edit: '
        if kind=='approval' and text.startswith(prefix):return self.tr('Awaiting approval for file edit: {path}').format(path=text[len(prefix):])
        for prefix,template in [('Approved proposal ',self.tr('Approved proposal {id}')),('Rejected proposal ',self.tr('Rejected proposal {id}'))]:
            if kind=='decision' and text.startswith(prefix):return template.format(id=text[len(prefix):])
        if kind=='output':
            prefix='Heavy task: requesting ';suffix=' through the selected connection.'
            if text.startswith(prefix) and text.endswith(suffix):return self.tr('Heavy task: requesting {model} through the selected connection.').format(model=text[len(prefix):-len(suffix)])
            prefix='Light task delegated to ';suffix=' through its configured connection.'
            if text.startswith(prefix) and text.endswith(suffix):return self.tr('Light task delegated to {model} through its configured connection.').format(model=text[len(prefix):-len(suffix)])
            prefix='Applied approved edit: '
            if text.startswith(prefix):return self.tr('Applied approved edit: {path}').format(path=text[len(prefix):])
        if kind=='usage':
            if text=='Usage: no model requests':return self.tr('Usage: no model requests')
            if text.startswith('Usage: '):
                parts=[]
                for part in text[7:].split('; '):
                    match=re.fullmatch(r'(Heavy|Light): (\d+) request\(s\), input (\d+(?:\.\d+)?|unknown)( \(known usage only\))?, output (\d+(?:\.\d+)?|unknown)( \(known usage only\))? tokens',part)
                    if not match:return text
                    role,count,incoming,in_partial,outgoing,out_partial=match.groups()
                    incoming=self.tr('unknown') if incoming=='unknown' else incoming
                    outgoing=self.tr('unknown') if outgoing=='unknown' else outgoing
                    partial=self.tr(' (known usage only)')
                    parts.append(self.tr('{role}: {count} request(s), input {incoming}{in_partial}, output {outgoing}{out_partial} tokens').format(role=self.tr('Heavy') if role=='Heavy' else self.tr('Light'),count=count,incoming=incoming,in_partial=partial if in_partial else '',outgoing=outgoing,out_partial=partial if out_partial else ''))
                return self.tr('Usage: {details}').format(details='; '.join(parts))
        return text

    def record(self,kind,text):
        history=self.session.setdefault('code_activity',[]);history.append({'kind':kind,'text':plain(text)})
        self.session['code_activity']=history[-32:];self.activity.setPlainText('\n'.join(self.activity_text(e) for e in self.session['code_activity']))
        self.store.save(self.session);self.updated.emit()

    def start_simulation(self):
        if self.job or self._closed:return
        self.launch(SimulationRun(self.session['path_snapshot']),'Simulation started; no commands or inference will run.')

    def receive(self,event):
        if self._closed or not self.job or event.get('run_id')!=self.run_id:return
        kind=event.get('kind')
        if kind=='source':
            source=event.get('source',{})
            try:
                ident=source['id'];title=source['title'];url=public_url(source['url'])
                if not isinstance(ident,str) or not re.fullmatch(r'S[1-9][0-9]{0,14}',ident) or not isinstance(title,str):return
                sources=self.session.setdefault('coding_sources',[])
                if len(sources)>=32:return
                sources.append({'id':ident,'title':plain(title)[:200],'url':url});self.store.save(self.session);self.update_sources_button()
            except (KeyError,TypeError,ValueError):return
        elif kind=='edit_proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            self.advice_fingerprint=None;self.advice_label.hide()
            proposal=event['proposal'];self.diff.setVisible(True);self.diff.setPlainText(proposal['diff'])
            self.approval.setPlainText(self.tr('FILE EDIT\nProject: {project}\nPath: {path}\nReview the full diff below.\nSafety recommendation: Not checked; no System One request was made.').format(project=proposal['cwd'],path=proposal['path']))
            self.approval_panel.show();self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting approval for file edit: '+proposal['path'])
        elif kind=='operation_proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval';proposal=event['proposal'];operation=proposal['operation']
            self.advice_fingerprint=self.pending_fingerprint if operation=='run_shell' else None
            if operation=='run_shell':self.show_advice()
            else:self.advice_label.hide()
            self.diff.setPlainText(proposal.get('diff',''));self.diff.setVisible(operation=='delete_file')
            if operation=='run_shell':
                text=self.tr('SHELL COMMAND\nWorking directory: {cwd}\nShell: {shell}\nTime limit: up to {seconds} seconds; output limit: {size} bytes.\nThe command runs with your account permissions, including network and access outside the project. It is not sandboxed.\nInherited environment variables: {environment}\n\nCommand:\n{command}').format(cwd=proposal['cwd'],shell=proposal['shell'],seconds=proposal['max_seconds'],size=proposal['max_output_bytes'],environment=', '.join(proposal['environment_keys']),command=proposal['command'])
            else:
                label=self.tr('DELETE FILE') if operation=='delete_file' else self.tr('CREATE DIRECTORY')
                text=self.tr('{operation}\nProject: {project}\nPath: {path}\nSafety recommendation: Not checked.').format(operation=label,project=proposal['cwd'],path=proposal['path'])
            self.approval.setPlainText(text);self.approval_panel.show();self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting approval: '+operation+' '+proposal.get('path',''))
            if operation=='run_shell' and self.advice_connection:self.check_advice(proposal,self.pending_fingerprint)
        elif kind=='proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            self.advice_fingerprint=None;self.advice_label.hide()
            proposal=event['proposal'];self.diff.setVisible(True)
            self.approval.setPlainText(self.tr('SIMULATION ONLY\nDirectory: {directory}\nArguments: {arguments}\nRecommendation: {recommendation}').format(directory=proposal['cwd'],arguments=json.dumps(proposal['argv']),recommendation=event['recommendation']))
            self.approval_panel.show();self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting explicit approval for simulated step.')
        elif kind=='diff':self.diff.setPlainText(plain(event['text']));self.record(kind,event['text'])
        elif kind=='output':self.record(kind,event['text'])
        elif kind=='finished':
            if event['status']=='completed' and isinstance(self.job,CodingRun):
                secrets=[self.job.connection.get('api_key',''),(self.job.light or {}).get('api_key','')]
                context={'task':plain(scrub(self.job.prompt,secrets)),'answer':plain(event['text'])}
                self.session['coding_context']=context
                self.context_view.setPlainText(self.context_text(context))
                self.use_context.setChecked(False)
            self.session['code_state']=event['status'];self.finish();self.record(kind,event['text'])
            if event.get('usage'):self.record('usage',event['usage'])

    def decide(self,allowed):
        if self.advice_job:return
        if self.job and self.pending_fingerprint and self.job.decide(self.pending_fingerprint,allowed):
            decision=self.pending_fingerprint;self.approve.setEnabled(False);self.reject.setEnabled(False);self.pending_fingerprint=None
            self.advice_fingerprint=None
            self.approval_panel.hide();self.approval.clear();self.diff.clear()
            self.session['code_state']='running';self.record('decision',('Approved' if allowed else 'Rejected')+' proposal '+decision)

    def finish(self):
        if self.advice_job:self.advice_job.cancel.set();self.advice_job=None
        self.advice_connection=None;self.advice_destination=''
        self.run_id=None;self.job=None;self.pending_fingerprint=None;self.advice_fingerprint=None
        self.approval_panel.hide()
        for button in (self.approve,self.reject,self.cancel_button):button.setEnabled(False)
        self.simulate.setEnabled(True);self.send.setEnabled(True)
        self.light_enabled.setEnabled(True);self.web_enabled.setEnabled(True);self.limits_button.setEnabled(True);self.search_settings.setEnabled(True);self.advice_enabled.setEnabled(True)
        self.use_context.setEnabled(bool(self.session.get('coding_context')))
        for connection,model in self.roles.values():connection.setEnabled(True);model.setEnabled(True)

    def cancel(self):
        if not self.job:return
        self.job.stop();self.session['code_state']='cancelled';self.finish()
        self.record('cancelled','Run cancelled. No further tool work will be scheduled; already approved edits are retained.')

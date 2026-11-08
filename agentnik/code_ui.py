"""Repository picker and Agentnik-owned coding pane."""
from pathlib import Path
import json
import threading
from PySide6.QtCore import Qt,Signal,QObject
from PySide6.QtWidgets import QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QPushButton,QDialogButtonBox,QFileDialog,QInputDialog,QMessageBox,QPlainTextEdit,QComboBox,QCheckBox
from .repositories import RepositoryRegistry
from .coding import SimulationRun,plain
from .code_agent import CodingRun
from .research import scrub
from . import core


class RepositoryPicker(QDialog):
    def __init__(self,parent,registry,select=True):
        super().__init__(parent);self.registry=registry;self.selected_id=None;self.select=select
        self.setWindowTitle('Choose repository' if select else 'Repositories');self.resize(680,400)
        layout=QVBoxLayout(self);self.search=QLineEdit();self.search.setPlaceholderText('Search project names and paths');layout.addWidget(self.search)
        self.items=QListWidget();layout.addWidget(self.items);self.search.textChanged.connect(self.refresh)
        actions=QHBoxLayout();layout.addLayout(actions)
        for label,fn in [('Add folder',self.add),('Rename',self.rename),('Locate folder',self.locate),('Remove from list',self.remove)]:
            button=QPushButton(label);button.clicked.connect(fn);actions.addWidget(button)
        self.hint=QLabel('Git is optional. Removing an entry never deletes files. Add a folder to begin.');self.hint.setWordWrap(True);layout.addWidget(self.hint)
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
            item=QListWidgetItem(row['name']+(' · missing/unavailable' if not row['available'] else '')+'\n'+row['path']);item.setData(Qt.ItemDataRole.UserRole,row['id']);self.items.addItem(item)
            if old and row['id']==old['id']:self.items.setCurrentItem(item)
        if self.items.currentRow()<0 and self.items.count():self.items.setCurrentRow(0)

    def attempt(self,fn):
        try:fn();self.refresh()
        except (OSError,ValueError) as exc:QMessageBox.warning(self,'Repositories',str(exc))

    def add(self):
        path=QFileDialog.getExistingDirectory(self,'Add project folder')
        if path:self.attempt(lambda:self.registry.put(path))

    def rename(self):
        row=self.selected()
        if not row:return
        name,ok=QInputDialog.getText(self,'Rename project','Name:',text=row['name'])
        if ok:self.attempt(lambda:self.registry.rename(row['id'],name))

    def locate(self):
        row=self.selected()
        if not row:return
        path=QFileDialog.getExistingDirectory(self,'Locate project folder')
        if path:self.attempt(lambda:self.registry.put(path,row['name'],row['id']))

    def remove(self):
        row=self.selected()
        if row and QMessageBox.question(self,'Remove project','Remove this entry from the list? Its files and history will remain.')==QMessageBox.StandardButton.Yes:
            self.attempt(lambda:self.registry.remove(row['id']))

    def choose(self):
        row=self.selected()
        if not row:return
        try:self.registry.directory(row['path'])
        except (OSError,ValueError) as exc:QMessageBox.warning(self,'Unavailable project',str(exc));return
        self.selected_id=row['id'];self.accept()


class CodeEvents(QObject):
    event=Signal(object)


class CodeTab(QWidget):
    updated=Signal()
    def __init__(self,window,session):
        super().__init__();self.window=window;self.store=window.store;self.session=session;self.job=None;self.model_jobs={};self._closed=False;self.run_id=None;self.pending_fingerprint=None
        self.events=CodeEvents(self);self.events.event.connect(self.receive)
        if session.get("code_state") in ("running","awaiting_approval"):
            session["code_state"]="interrupted"
            session.setdefault("code_activity",[]).append({"kind":"interrupted","text":"Interrupted coding run; nothing resumes automatically."})
            session["code_activity"]=session["code_activity"][-32:]
            self.store.save(session)
        layout=QVBoxLayout(self)
        title=QLabel(session['project_name']);title.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(title)
        path=QLabel('Working directory snapshot: '+session['path_snapshot']);path.setTextFormat(Qt.TextFormat.PlainText);path.setWordWrap(True);layout.addWidget(path)
        current=window.repositories.get(session['project_id'])
        note='Agentnik coding uses your selected models. File reads are sent to the selected endpoint. Edits require approval; shell execution is unavailable. A configured light model may receive delegated context at its own endpoint.'
        if not Path(session['path_snapshot']).is_dir():note+=' The saved folder is missing or unavailable.'
        if current is None:note+=' This project was removed from the registry; its history is retained.'
        elif current['path']!=session['path_snapshot']:note+=' The registered folder moved. This session retains its original path; open a new Code pane to use the relocated folder.'
        info=QLabel(note);info.setWordWrap(True);layout.addWidget(info)
        self.activity=QPlainTextEdit('\n'.join(plain(e.get('text',e.get('kind',''))) for e in session.get('code_activity',[])) or 'No commands have been run.');self.activity.setReadOnly(True);layout.addWidget(self.activity,1)
        self.composer=QPlainTextEdit(session.get('draft',''));self.composer.setPlaceholderText('Describe the coding task; repository files may be sent to the selected models');layout.addWidget(self.composer)
        context=session.get('coding_context')
        self.context_view=QPlainTextEdit(('Previous task:\n'+context['task']+'\n\nPrevious answer:\n'+context['answer']) if context else 'No completed coding task available.')
        self.context_view.setReadOnly(True);self.context_view.setMaximumHeight(110);layout.addWidget(self.context_view)
        self.use_context=QCheckBox('Send previous task and answer with next run (up to 2,048 characters each)');self.use_context.setEnabled(bool(context));layout.addWidget(self.use_context)
        self.roles={}
        bindings=session.get('coding_models',{})
        for role in ('heavy','light'):
            row=QHBoxLayout();layout.addLayout(row);row.addWidget(QLabel(role.title()+' model'))
            connection=QComboBox();connection.addItem('Not configured','');
            for name in window.connections:connection.addItem(name,name)
            model=QLineEdit();model.setPlaceholderText('Model alias (any supported coding model)')
            saved=bindings.get(role,{})
            missing=saved.get('connection','')
            if missing and connection.findData(missing)<0:connection.addItem(missing+' (unavailable)',missing)
            connection.setCurrentIndex(max(0,connection.findData(saved.get('connection',''))));model.setText(saved.get('model',''))
            row.addWidget(connection);row.addWidget(model,1);self.roles[role]=(connection,model)
            choose=QPushButton('Choose model…');choose.clicked.connect(lambda _,r=role:self.choose_model(r));row.addWidget(choose)
            connection.currentIndexChanged.connect(lambda _,r=role:self.role_changed(r))
            model.editingFinished.connect(self.save_models)
        self.light_enabled=QCheckBox('Allow Light model delegation');self.light_enabled.setChecked(session.get('coding_light_enabled',True) is not False);layout.addWidget(self.light_enabled)
        self.light_enabled.toggled.connect(self.save_light_enabled)
        self.send=QPushButton('Run coding task');self.send.clicked.connect(self.start_coding);layout.addWidget(self.send)
        self.simulate=QPushButton('Try simulated workflow (no execution)');self.simulate.clicked.connect(self.start_simulation);layout.addWidget(self.simulate)
        self.approval=QPlainTextEdit();self.approval.setReadOnly(True);self.approval.setPlaceholderText('Command approval preview');layout.addWidget(self.approval)
        actions=QHBoxLayout();layout.addLayout(actions)
        self.approve=QPushButton('Approve proposed step');self.reject=QPushButton('Reject proposed step');self.cancel_button=QPushButton('Cancel run')
        for button in (self.approve,self.reject,self.cancel_button):actions.addWidget(button);button.setEnabled(False)
        self.approve.clicked.connect(lambda:self.decide(True));self.reject.clicked.connect(lambda:self.decide(False));self.cancel_button.clicked.connect(self.cancel)
        self.diff=QPlainTextEdit();self.diff.setReadOnly(True);self.diff.setPlaceholderText('Review the complete proposed file diff before approving');layout.addWidget(self.diff)
        self.composer.textChanged.connect(self.save_draft)

    def choose_model(self,role):
        if self.job or role in self.model_jobs:return
        name=self.roles[role][0].currentData()
        if not name:return QMessageBox.information(self,'Coding model','Choose a connection first, or enter an alias manually.')
        c=dict(self.window.connections.get(name,{}))
        from .ui import Job
        def done(names):
            self.model_jobs.pop(role,None)
            if self._closed or self.job or self.roles[role][0].currentData()!=name:return
            choices=[value for value in names if isinstance(value,str) and len(value)<=512][:2000]
            model,ok=QInputDialog.getItem(self,'Choose '+role+' model','Model alias:',choices,0,True)
            if ok:self.roles[role][1].setText(model);self.save_models()
        def failed(_):
            self.model_jobs.pop(role,None)
            if not self._closed:QMessageBox.warning(self,'Coding models','Model listing failed. You can enter an alias manually.')
        self.model_jobs[role]=Job(lambda *_:core.models(c),done,failed)

    def role_changed(self,role):
        connection,model=self.roles[role];c=self.window.connections.get(connection.currentData(),{})
        model.setText(c.get('model',''));self.save_models()

    def save_models(self):
        self.session['coding_models']={role:{'connection':widgets[0].currentData(),'model':widgets[1].text().strip()} for role,widgets in self.roles.items()}
        self.store.save(self.session)

    def save_light_enabled(self,enabled):
        self.session['coding_light_enabled']=enabled;self.store.save(self.session)

    def role_connection(self,role):
        name=self.roles[role][0].currentData()
        if not name:return None
        c=dict(self.window.connections.get(name,{}));c['model']=self.roles[role][1].text().strip()
        if not c.get('url') or not c.get('model'):raise ValueError('Choose a connection and model alias for '+role)
        return c

    def start_coding(self):
        if self.job or self._closed:return
        try:
            self.save_models();heavy=self.role_connection('heavy');light=self.role_connection('light') if self.light_enabled.isChecked() else None
            if not heavy or not self.composer.toPlainText().strip():raise ValueError('Choose a heavy model and enter a coding task')
            context=self.session.get('coding_context') if self.use_context.isChecked() else None
            run=CodingRun(heavy,self.session['path_snapshot'],self.composer.toPlainText(),light,context)
        except ValueError as exc:QMessageBox.warning(self,'Coding settings',str(exc));return
        self.launch(run,'Agentnik coding started. Repository content goes to the selected models; edits await approval.')

    def launch(self,run,notice):
        self.job=run;self.run_id=run.run_id;self.pending_fingerprint=None;self.session['code_state']='running'
        self.simulate.setEnabled(False);self.send.setEnabled(False);self.cancel_button.setEnabled(True)
        self.light_enabled.setEnabled(False)
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

    def record(self,kind,text):
        history=self.session.setdefault('code_activity',[]);history.append({'kind':kind,'text':plain(text)})
        self.session['code_activity']=history[-32:];self.activity.setPlainText('\n'.join(e['text'] for e in self.session['code_activity']))
        self.store.save(self.session);self.updated.emit()

    def start_simulation(self):
        if self.job or self._closed:return
        self.launch(SimulationRun(self.session['path_snapshot']),'Simulation started; no commands or inference will run.')

    def receive(self,event):
        if self._closed or not self.job or event.get('run_id')!=self.run_id:return
        kind=event.get('kind')
        if kind=='edit_proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            proposal=event['proposal'];self.diff.setPlainText(proposal['diff'])
            self.approval.setPlainText('FILE EDIT\nProject: '+proposal['cwd']+'\nPath: '+proposal['path']+'\nReview the full diff below.\nSafety recommendation: Not checked; no System One request was made.')
            self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting approval for file edit: '+proposal['path'])
        elif kind=='proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            proposal=event['proposal']
            self.approval.setPlainText('SIMULATION ONLY\nDirectory: '+proposal['cwd']+'\nArguments: '+json.dumps(proposal['argv'])+'\nRecommendation: '+event['recommendation'])
            self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting explicit approval for simulated step.')
        elif kind=='diff':self.diff.setPlainText(plain(event['text']));self.record(kind,event['text'])
        elif kind=='output':self.record(kind,event['text'])
        elif kind=='finished':
            if event['status']=='completed' and isinstance(self.job,CodingRun):
                secrets=[self.job.connection.get('api_key',''),(self.job.light or {}).get('api_key','')]
                context={'task':plain(scrub(self.job.prompt,secrets)),'answer':plain(event['text'])}
                self.session['coding_context']=context
                self.context_view.setPlainText('Previous task:\n'+context['task']+'\n\nPrevious answer:\n'+context['answer'])
                self.use_context.setChecked(False)
            self.session['code_state']=event['status'];self.finish();self.record(kind,event['text'])
            if event.get('usage'):self.record('usage',event['usage'])

    def decide(self,allowed):
        if self.job and self.pending_fingerprint and self.job.decide(self.pending_fingerprint,allowed):
            decision=self.pending_fingerprint;self.approve.setEnabled(False);self.reject.setEnabled(False);self.pending_fingerprint=None
            self.session['code_state']='running';self.record('decision',('Approved' if allowed else 'Rejected')+' proposal '+decision)

    def finish(self):
        self.run_id=None;self.job=None;self.pending_fingerprint=None
        for button in (self.approve,self.reject,self.cancel_button):button.setEnabled(False)
        self.simulate.setEnabled(True);self.send.setEnabled(True)
        self.light_enabled.setEnabled(True)
        self.use_context.setEnabled(bool(self.session.get('coding_context')))
        for connection,model in self.roles.values():connection.setEnabled(True);model.setEnabled(True)

    def cancel(self):
        if not self.job:return
        self.job.stop();self.session['code_state']='cancelled';self.finish()
        self.record('cancelled','Run cancelled. No further tool work will be scheduled; already approved edits are retained.')

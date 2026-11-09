"""Repository picker and Agentnik-owned coding pane."""
from pathlib import Path
import json
import re
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
        path=QLabel(self.tr('Working directory snapshot: {path}').format(path=session['path_snapshot']));path.setTextFormat(Qt.TextFormat.PlainText);path.setWordWrap(True);layout.addWidget(path)
        current=window.repositories.get(session['project_id'])
        note=self.tr('Agentnik coding uses your selected models. File reads are sent to the selected endpoint. Edits require approval; shell execution is unavailable. A configured light model may receive delegated context at its own endpoint.')
        if not Path(session['path_snapshot']).is_dir():note+=' '+self.tr('The saved folder is missing or unavailable.')
        if current is None:note+=' '+self.tr('This project was removed from the registry; its history is retained.')
        elif current['path']!=session['path_snapshot']:note+=' '+self.tr('The registered folder moved. This session retains its original path; open a new Code pane to use the relocated folder.')
        info=QLabel(note);info.setWordWrap(True);layout.addWidget(info)
        self.activity=QPlainTextEdit('\n'.join(self.activity_text(e) for e in session.get('code_activity',[])) or self.tr('No commands have been run.'));self.activity.setReadOnly(True);layout.addWidget(self.activity,1)
        self.composer=QPlainTextEdit(session.get('draft',''));self.composer.setPlaceholderText(self.tr('Describe the coding task; repository files may be sent to the selected models'));layout.addWidget(self.composer)
        context=session.get('coding_context')
        self.context_view=QPlainTextEdit(self.context_text(context))
        self.context_view.setReadOnly(True);self.context_view.setMaximumHeight(110);layout.addWidget(self.context_view)
        self.use_context=QCheckBox(self.tr('Send previous task and answer with next run (up to 2,048 characters each)'));self.use_context.setEnabled(bool(context));layout.addWidget(self.use_context)
        self.roles={}
        bindings=session.get('coding_models',{})
        for role in ('heavy','light'):
            row=QHBoxLayout();layout.addLayout(row);row.addWidget(QLabel(self.tr('Heavy model') if role=='heavy' else self.tr('Light model')))
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
        self.light_enabled=QCheckBox(self.tr('Allow Light model delegation'));self.light_enabled.setChecked(session.get('coding_light_enabled',True) is not False);layout.addWidget(self.light_enabled)
        self.light_enabled.toggled.connect(self.save_light_enabled)
        self.send=QPushButton(self.tr('Run coding task'));self.send.clicked.connect(self.start_coding);layout.addWidget(self.send)
        self.simulate=QPushButton(self.tr('Try simulated workflow (no execution)'));self.simulate.clicked.connect(self.start_simulation);layout.addWidget(self.simulate)
        self.approval=QPlainTextEdit();self.approval.setReadOnly(True);self.approval.setPlaceholderText(self.tr('Command approval preview'));layout.addWidget(self.approval)
        actions=QHBoxLayout();layout.addLayout(actions)
        self.approve=QPushButton(self.tr('Approve proposed step'));self.reject=QPushButton(self.tr('Reject proposed step'));self.cancel_button=QPushButton(self.tr('Cancel run'))
        for button in (self.approve,self.reject,self.cancel_button):actions.addWidget(button);button.setEnabled(False)
        self.approve.clicked.connect(lambda:self.decide(True));self.reject.clicked.connect(lambda:self.decide(False));self.cancel_button.clicked.connect(self.cancel)
        self.diff=QPlainTextEdit();self.diff.setReadOnly(True);self.diff.setPlaceholderText(self.tr('Review the complete proposed file diff before approving'));layout.addWidget(self.diff)
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
            title=self.tr('Choose Heavy model') if role=='heavy' else self.tr('Choose Light model')
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
        self.session['coding_models']={role:{'connection':widgets[0].currentData(),'model':widgets[1].text().strip()} for role,widgets in self.roles.items()}
        self.store.save(self.session)

    def save_light_enabled(self,enabled):
        self.session['coding_light_enabled']=enabled;self.store.save(self.session)

    def role_connection(self,role):
        name=self.roles[role][0].currentData()
        if not name:return None
        c=dict(self.window.connections.get(name,{}));c['model']=self.roles[role][1].text().strip()
        if not c.get('url') or not c.get('model'):
            raise ValueError(self.tr('Choose a connection and model alias for Heavy.') if role=='heavy' else self.tr('Choose a connection and model alias for Light.'))
        return c

    def start_coding(self):
        if self.job or self._closed:return
        try:
            self.save_models();heavy=self.role_connection('heavy');light=self.role_connection('light') if self.light_enabled.isChecked() else None
            if not heavy or not self.composer.toPlainText().strip():raise ValueError(self.tr('Choose a heavy model and enter a coding task'))
            context=self.session.get('coding_context') if self.use_context.isChecked() else None
            run=CodingRun(heavy,self.session['path_snapshot'],self.composer.toPlainText(),light,context)
        except ValueError as exc:QMessageBox.warning(self,self.tr('Coding settings'),str(exc));return
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
        if kind=='edit_proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            proposal=event['proposal'];self.diff.setPlainText(proposal['diff'])
            self.approval.setPlainText(self.tr('FILE EDIT\nProject: {project}\nPath: {path}\nReview the full diff below.\nSafety recommendation: Not checked; no System One request was made.').format(project=proposal['cwd'],path=proposal['path']))
            self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting approval for file edit: '+proposal['path'])
        elif kind=='proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            proposal=event['proposal']
            self.approval.setPlainText(self.tr('SIMULATION ONLY\nDirectory: {directory}\nArguments: {arguments}\nRecommendation: {recommendation}').format(directory=proposal['cwd'],arguments=json.dumps(proposal['argv']),recommendation=event['recommendation']))
            self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting explicit approval for simulated step.')
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

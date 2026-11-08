"""Passive repository picker and Code pane; no inference or process backend."""
from pathlib import Path
import json
import threading
from PySide6.QtCore import Qt,Signal,QObject
from PySide6.QtWidgets import QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QPushButton,QDialogButtonBox,QFileDialog,QInputDialog,QMessageBox,QPlainTextEdit
from .repositories import RepositoryRegistry
from .coding import SimulationRun,plain


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
        super().__init__();self.window=window;self.store=window.store;self.session=session;self.job=None;self._closed=False;self.run_id=None;self.pending_fingerprint=None
        self.events=CodeEvents(self);self.events.event.connect(self.receive)
        if session.get("code_state") in ("running","awaiting_approval"):
            session["code_state"]="interrupted"
            session.setdefault("code_activity",[]).append({"kind":"interrupted","text":"Interrupted simulation; nothing resumes automatically."})
            session["code_activity"]=session["code_activity"][-32:]
            self.store.save(session)
        layout=QVBoxLayout(self)
        title=QLabel(session['project_name']);title.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(title)
        path=QLabel('Working directory snapshot: '+session['path_snapshot']);path.setTextFormat(Qt.TextFormat.PlainText);path.setWordWrap(True);layout.addWidget(path)
        current=window.repositories.get(session['project_id'])
        note='Coding backend not connected. Commands and inference are unavailable. Drafts are saved locally.'
        if not Path(session['path_snapshot']).is_dir():note+=' The saved folder is missing or unavailable.'
        if current is None:note+=' This project was removed from the registry; its history is retained.'
        elif current['path']!=session['path_snapshot']:note+=' The registered folder moved. This session retains its original path; open a new Code pane to use the relocated folder.'
        info=QLabel(note);info.setWordWrap(True);layout.addWidget(info)
        self.activity=QPlainTextEdit('\n'.join(plain(e.get('text',e.get('kind',''))) for e in session.get('code_activity',[])) or 'No commands have been run.');self.activity.setReadOnly(True);layout.addWidget(self.activity,1)
        self.composer=QPlainTextEdit(session.get('draft',''));self.composer.setPlaceholderText('Draft a coding task (saved only; backend not connected)');layout.addWidget(self.composer)
        send=QPushButton('Run · backend not connected');send.setEnabled(False);layout.addWidget(send)
        self.simulate=QPushButton('Try simulated workflow (no execution)');self.simulate.clicked.connect(self.start_simulation);layout.addWidget(self.simulate)
        self.approval=QPlainTextEdit();self.approval.setReadOnly(True);self.approval.setPlaceholderText('Command approval preview');layout.addWidget(self.approval)
        actions=QHBoxLayout();layout.addLayout(actions)
        self.approve=QPushButton('Approve simulated step');self.reject=QPushButton('Reject simulated step');self.cancel_button=QPushButton('Cancel simulation')
        for button in (self.approve,self.reject,self.cancel_button):actions.addWidget(button);button.setEnabled(False)
        self.approve.clicked.connect(lambda:self.decide(True));self.reject.clicked.connect(lambda:self.decide(False));self.cancel_button.clicked.connect(self.cancel)
        self.diff=QPlainTextEdit();self.diff.setReadOnly(True);self.diff.setPlaceholderText('Proposed changes review (simulation only)');layout.addWidget(self.diff)
        self.composer.textChanged.connect(self.save_draft)

    def save_draft(self):
        self.session['draft']=self.composer.toPlainText();self.store.save(self.session);self.updated.emit()

    def record(self,kind,text):
        history=self.session.setdefault('code_activity',[]);history.append({'kind':kind,'text':plain(text)})
        self.session['code_activity']=history[-32:];self.activity.setPlainText('\n'.join(e['text'] for e in self.session['code_activity']))
        self.store.save(self.session);self.updated.emit()

    def start_simulation(self):
        if self.job or self._closed:return
        self.job=SimulationRun(self.session['path_snapshot']);self.run_id=self.job.run_id
        self.session['code_state']='running';self.diff.clear();self.approval.clear();self.pending_fingerprint=None
        self.simulate.setEnabled(False);self.cancel_button.setEnabled(True)
        self.record('started','Simulation started; no commands or inference will run.')
        signals=self.events;run=self.job
        def work():
            try:run.run(signals.event.emit)
            except RuntimeError:pass  # The pane may have been destroyed after cancellation.
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def receive(self,event):
        if self._closed or not self.job or event.get('run_id')!=self.run_id:return
        kind=event.get('kind')
        if kind=='proposal':
            self.pending_fingerprint=event['fingerprint'];self.session['code_state']='awaiting_approval'
            proposal=event['proposal']
            self.approval.setPlainText('SIMULATION ONLY\nDirectory: '+proposal['cwd']+'\nArguments: '+json.dumps(proposal['argv'])+'\nRecommendation: '+event['recommendation'])
            self.approve.setEnabled(True);self.reject.setEnabled(True);self.record('approval','Awaiting explicit approval for simulated step.')
        elif kind=='diff':self.diff.setPlainText(plain(event['text']));self.record(kind,event['text'])
        elif kind=='output':self.record(kind,event['text'])
        elif kind=='finished':
            self.session['code_state']=event['status'];self.finish();self.record(kind,event['text'])

    def decide(self,allowed):
        if self.job and self.pending_fingerprint and self.job.decide(self.pending_fingerprint,allowed):
            self.approve.setEnabled(False);self.reject.setEnabled(False);self.pending_fingerprint=None

    def finish(self):
        self.run_id=None;self.job=None;self.pending_fingerprint=None
        for button in (self.approve,self.reject,self.cancel_button):button.setEnabled(False)
        self.simulate.setEnabled(True)

    def cancel(self):
        if not self.job:return
        self.job.stop();self.session['code_state']='cancelled';self.finish()
        self.record('cancelled','Simulation cancelled. No command ran.')

"""Passive repository picker and Code pane; no inference or process backend."""
from pathlib import Path
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QPushButton,QDialogButtonBox,QFileDialog,QInputDialog,QMessageBox,QPlainTextEdit
from .repositories import RepositoryRegistry


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


class CodeTab(QWidget):
    updated=Signal()
    def __init__(self,window,session):
        super().__init__();self.window=window;self.store=window.store;self.session=session;self.job=None;self._closed=False
        layout=QVBoxLayout(self)
        title=QLabel(session['project_name']);title.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(title)
        path=QLabel('Working directory snapshot: '+session['path_snapshot']);path.setTextFormat(Qt.TextFormat.PlainText);path.setWordWrap(True);layout.addWidget(path)
        current=window.repositories.get(session['project_id'])
        note='Coding backend not connected. Commands and inference are unavailable. Drafts are saved locally.'
        if not Path(session['path_snapshot']).is_dir():note+=' The saved folder is missing or unavailable.'
        if current is None:note+=' This project was removed from the registry; its history is retained.'
        elif current['path']!=session['path_snapshot']:note+=' The registered folder moved. This session retains its original path; open a new Code pane to use the relocated folder.'
        info=QLabel(note);info.setWordWrap(True);layout.addWidget(info)
        self.activity=QPlainTextEdit('No commands have been run.');self.activity.setReadOnly(True);layout.addWidget(self.activity,1)
        self.composer=QPlainTextEdit(session.get('draft',''));self.composer.setPlaceholderText('Draft a coding task (saved only; backend not connected)');layout.addWidget(self.composer)
        send=QPushButton('Run · backend not connected');send.setEnabled(False);layout.addWidget(send)
        self.composer.textChanged.connect(self.save_draft)

    def save_draft(self):
        self.session['draft']=self.composer.toPlainText();self.store.save(self.session);self.updated.emit()

    def cancel(self):pass

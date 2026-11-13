"""Review-bound edits of durable tracks, with conflict and partial-run checks."""
import copy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles
from agentnik.track_editing import load_edit,apply_edit,validate_edit

FIXTURE=Path(__file__).parent/'fixtures'/'tracks'

class TrackEditing(unittest.TestCase):
    def project(self,root):
        project=Path(root)/'project';shutil.copytree(FIXTURE,project);return project
    def test_unchanged_files_are_never_rewritten(self):
        with tempfile.TemporaryDirectory() as root:
            project=self.project(root);base=project/'agentnik-plans'/'tracks'/'sample_feature'
            for p in base.iterdir():p.write_bytes(p.read_bytes().replace(b'\n',b'\r\n'))
            before={p.name:p.read_bytes() for p in base.iterdir()};files=ProjectFiles(project);draft=load_edit(files,'sample_feature');calls=[]
            result=apply_edit(files,draft,lambda value:calls.append(value) or True)
            self.assertEqual(result['applied'],[]);self.assertEqual(calls,[]);self.assertEqual(before,{p.name:p.read_bytes() for p in base.iterdir()})

    def test_individual_approvals_partial_resume_and_metadata_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            project=self.project(root);base=project/'agentnik-plans'/'tracks'/'sample_feature';metadata=(base/'track.json').read_bytes();files=ProjectFiles(project);draft=load_edit(files,'sample_feature');draft['files']['spec.md']+='\nExtra requirement.\n';draft['files']['plan.md']+='\nAnother phase.\n';states=[]
            def approve(proposal):return not proposal['path'].endswith('plan.md')
            result=apply_edit(files,draft,approve,lambda value:states.append(copy.deepcopy(value)))
            self.assertEqual(result['status'],'rejected');self.assertEqual(len(result['applied']),1);self.assertIn('Extra requirement',(base/'spec.md').read_text(encoding='utf-8'));self.assertNotIn('Another phase',(base/'plan.md').read_text(encoding='utf-8'))
            resumed=apply_edit(files,states[-1],lambda _:True);self.assertEqual(resumed['status'],'completed');self.assertEqual(len(resumed['applied']),1);self.assertEqual((base/'track.json').read_bytes(),metadata)

    def test_stale_other_file_and_concurrent_review_changes_stop_write(self):
        with tempfile.TemporaryDirectory() as root:
            project=self.project(root);base=project/'agentnik-plans'/'tracks'/'sample_feature';files=ProjectFiles(project);draft=load_edit(files,'sample_feature');draft['files']['spec.md']+='\nEdit\n';original=(base/'spec.md').read_bytes()
            (base/'plan.md').write_text('external',encoding='utf-8')
            with self.assertRaises(ValueError):apply_edit(files,draft,lambda _:True)
            self.assertEqual((base/'spec.md').read_bytes(),original)
            draft=load_edit(files,'sample_feature');draft['files']['spec.md']+='\nEdit\n'
            def approve(_):
                (base/'plan.md').write_text('changed during approval',encoding='utf-8');return True
            with self.assertRaises(ValueError):apply_edit(files,draft,approve)
            self.assertEqual((base/'spec.md').read_bytes(),original);self.assertEqual((base/'plan.md').read_text(encoding='utf-8'),'changed during approval')

    def test_rejects_invalid_or_other_track_metadata_and_review_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            project=self.project(root);files=ProjectFiles(project);draft=load_edit(files,'sample_feature');bad=copy.deepcopy(draft);bad['files']['track.json']=bad['files']['track.json'].replace('sample_feature','other')
            with self.assertRaises(ValueError):validate_edit(bad)
            draft['files']['spec.md']+='\nIntended\n'
            def approve(proposal):proposal['content']='bad';return True
            apply_edit(files,draft,approve);self.assertIn('Intended',(project/'agentnik-plans'/'tracks'/'sample_feature'/'spec.md').read_text(encoding='utf-8'))

    def test_ui_draft_preserves_crlf_and_reopens(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QPushButton
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=self.project(root);base=project/'agentnik-plans'/'tracks'/'sample_feature';metadata=base/'track.json';metadata.write_bytes(metadata.read_bytes().replace(b'\n',b'\r\n'));original=metadata.read_bytes()
            store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def save():
                    dialog=app.activeModalWidget();next(b for b in dialog.findChildren(QPushButton) if b.text()=='Save edit draft').click();dialog.reject()
                QTimer.singleShot(0,save);tab.edit_existing_track('sample_feature');saved=store.list_sessions()[0]
                self.assertEqual(saved['track_edit_draft']['files']['track.json'].encode(),original);self.assertEqual(metadata.read_bytes(),original)
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);tab=window.tabs.currentWidget();self.assertEqual(tab.session['track_edit_draft']['id'],'sample_feature')
            finally:window.close();app.processEvents();store.db.close()

    def test_ui_rejects_change_and_keeps_resumable_draft(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QPushButton,QTabWidget,QPlainTextEdit
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=self.project(root);path=project/'agentnik-plans'/'tracks'/'sample_feature'/'spec.md';before=path.read_bytes();store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def edit():
                    dialog=app.activeModalWidget();dialog.findChild(QTabWidget).widget(1).setPlainText('New requirements\n')
                    def reject():
                        review=app.activeModalWidget();self.assertIn('+New requirements',review.findChild(QPlainTextEdit).toPlainText());review.reject()
                    QTimer.singleShot(0,reject);next(b for b in dialog.findChildren(QPushButton) if b.text()=='Review changes…').click();dialog.reject()
                QTimer.singleShot(0,edit);tab.edit_existing_track('sample_feature')
                self.assertEqual(path.read_bytes(),before);self.assertEqual(store.list_sessions()[0]['track_edit_draft']['files']['spec.md'],'New requirements\n')
            finally:window.close();app.processEvents();store.db.close()
    def test_ui_approves_each_changed_file_and_clears_finished_draft(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QPushButton,QTabWidget,QPlainTextEdit,QDialogButtonBox
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([]);seen=[];errors=[]
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=self.project(root);base=project/'agentnik-plans'/'tracks'/'sample_feature';metadata=(base/'track.json').read_bytes();store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def approve():
                    try:
                        dialog=app.activeModalWidget();seen.append(dialog.findChild(QPlainTextEdit).toPlainText());dialog.accept()
                        if len(seen)<2:QTimer.singleShot(0,approve)
                    except Exception as exc:errors.append(repr(exc));dialog.reject()
                def edit():
                    try:
                        dialog=app.activeModalWidget();tabs=dialog.findChild(QTabWidget);tabs.widget(1).setPlainText('Updated spec\n');tabs.widget(2).setPlainText('Updated plan\n')
                        QTimer.singleShot(0,approve);next(b for b in dialog.findChildren(QPushButton) if b.text()=='Review changes…').click()
                    except Exception as exc:errors.append(repr(exc));dialog.reject()
                with patch('agentnik.code_ui.QMessageBox.information'):
                    QTimer.singleShot(0,edit);tab.edit_existing_track('sample_feature')
                self.assertEqual(errors,[]);self.assertEqual(len(seen),2);self.assertIn('+Updated spec',seen[0]);self.assertIn('+Updated plan',seen[1]);self.assertEqual((base/'track.json').read_bytes(),metadata)
                self.assertNotIn('track_edit_draft',store.list_sessions()[0]);self.assertEqual((base/'spec.md').read_text(encoding='utf-8'),'Updated spec\n')
            finally:window.close();app.processEvents();store.db.close()

"""Track reconciliation is explicit, bounded and review-bound."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles
from agentnik.track_execution import prepare_track,initial_progress,update_progress
from agentnik.track_editing import apply_edit
from agentnik.track_reconciliation import reconcile

FIXTURE=Path(__file__).parent/'fixtures'/'tracks'

class TrackReconciliation(unittest.TestCase):
    def setup_project(self,root):
        project=Path(root)/'project';shutil.copytree(FIXTURE,project);files=ProjectFiles(project)
        progress=initial_progress(prepare_track(files,'sample_feature'))
        progress=update_progress(progress,[{'id':'implement','status':'completed','detail':'Claims complete'},{'id':'verify','status':'in_progress','detail':'Checking'}])
        choices=[{'id':item['id'],'status':item['status'],'evidence':None} for item in initial_progress(prepare_track(files,'sample_feature'))['tasks']]
        return project,files,progress,choices

    def test_user_choices_require_evidence_and_preserve_metadata_format(self):
        with tempfile.TemporaryDirectory() as root:
            project,files,progress,choices=self.setup_project(root);path=project/'agentnik-plans/tracks/sample_feature/track.json';before=path.read_bytes()
            choices[1]['status']='completed';choices[2]['status']='in_progress'
            with self.assertRaisesRegex(ValueError,'passed evidence'):reconcile(files,progress,choices)
            choices[1]['evidence']=[{'status':'failed','detail':'Tests failed'}]
            with self.assertRaisesRegex(ValueError,'passed evidence'):reconcile(files,progress,choices)
            choices[1]['evidence']=[{'status':'passed','detail':'User inspected the implementation'}]
            draft=reconcile(files,progress,choices);self.assertEqual(path.read_bytes(),before)
            text=draft['files']['track.json'];self.assertIn('"phase": "Discovery", "step":',text)
            record=json.loads(text);self.assertEqual(record['tasks'][1]['status'],'completed');self.assertEqual(record['tasks'][2]['status'],'in_progress');self.assertEqual(record['tasks'][0]['evidence'][0]['status'],'unknown')
            rejected=apply_edit(files,draft,lambda _:False);self.assertEqual(rejected['status'],'rejected');self.assertEqual(path.read_bytes(),before)
            approved=apply_edit(files,draft,lambda _:True);self.assertEqual(len(approved['applied']),1);self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['tasks'][1]['evidence'][0]['status'],'passed')

    def test_stale_sources_and_invalid_choices_stop_reconciliation(self):
        with tempfile.TemporaryDirectory() as root:
            project,files,progress,choices=self.setup_project(root)
            invalid=list(choices);invalid[0]=dict(invalid[0],id='other')
            with self.assertRaises(ValueError):reconcile(files,progress,invalid)
            (project/'agentnik-plans/context.md').write_text('new context',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'changed since'):reconcile(files,progress,choices)

    def test_gui_user_selects_evidence_and_approves_diff(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QComboBox,QLineEdit,QPlainTextEdit,QPushButton
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([]);errors=[];seen=[]
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project,files,progress,choices=self.setup_project(root);store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['track_progress']=progress;store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def approve():
                    dialog=app.activeModalWidget()
                    try:seen.append(dialog.findChild(QPlainTextEdit).toPlainText());dialog.accept()
                    except Exception as exc:errors.append(repr(exc));dialog.reject()
                def choose():
                    dialog=app.activeModalWidget()
                    try:
                        boxes=dialog.findChildren(QComboBox);boxes[2].setCurrentText('completed');boxes[3].setCurrentIndex(1);boxes[4].setCurrentText('in_progress');dialog.findChildren(QLineEdit)[1].setText('Manually checked')
                        QTimer.singleShot(0,approve);next(button for button in dialog.findChildren(QPushButton) if button.text()=='Review status changes…').click()
                    except Exception as exc:errors.append(repr(exc));dialog.reject()
                with patch('agentnik.code_ui.QMessageBox.information'):
                    QTimer.singleShot(0,choose);tab.reconcile_track_progress()
                self.assertFalse(errors,errors);self.assertIn('Manually checked',seen[0]);data=json.loads((project/'agentnik-plans/tracks/sample_feature/track.json').read_text(encoding='utf-8'));self.assertEqual(data['tasks'][1]['status'],'completed')
            finally:window.close();app.processEvents();store.db.close()

    def test_gui_rechecks_context_after_diff_approval(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QComboBox,QPushButton
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([]);errors=[]
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project,files,progress,choices=self.setup_project(root);path=project/'agentnik-plans/tracks/sample_feature/track.json';before=path.read_bytes();store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['track_progress']=progress;store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def approve():
                    dialog=app.activeModalWidget()
                    try:(project/'agentnik-plans/context.md').write_text('changed during approval',encoding='utf-8');dialog.accept()
                    except Exception as exc:errors.append(repr(exc));dialog.reject()
                def choose():
                    dialog=app.activeModalWidget()
                    try:
                        dialog.findChildren(QComboBox)[2].setCurrentText('blocked')
                        QTimer.singleShot(0,approve);next(button for button in dialog.findChildren(QPushButton) if button.text()=='Review status changes…').click();dialog.reject()
                    except Exception as exc:errors.append(repr(exc));dialog.reject()
                with patch('agentnik.code_ui.QMessageBox.warning') as warning:
                    QTimer.singleShot(0,choose);tab.reconcile_track_progress();self.assertIn('changed during review',str(warning.call_args))
                self.assertFalse(errors,errors);self.assertEqual(path.read_bytes(),before)
            finally:window.close();app.processEvents();store.db.close()

"""Offline reviewed creation of session-owned track drafts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from agentnik.code_agent import ProjectFiles
from agentnik.track_authoring import new_draft,validate_draft,publish
from agentnik.tracks import list_tracks,read_track

class TrackAuthoring(unittest.TestCase):
    def test_approvals_and_creation_are_individual_and_metadata_last(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);events=[];persisted=[];draft=new_draft()
            def approve(proposal):events.append(copy.deepcopy(proposal));return True
            result=publish(files,draft,approve,lambda state:persisted.append(copy.deepcopy(state)))
            self.assertEqual(result['status'],'completed');self.assertEqual(len(events),6)
            self.assertEqual([e.get('operation','file') for e in events],['create_directory']*3+['file']*3)
            self.assertTrue(events[-1]['path'].endswith('track.json'));self.assertIn('+  "version": 1',events[-1]['diff'])
            self.assertEqual(len(persisted[-1]['written']),3);self.assertEqual(read_track(files,'new_track')['track']['title'],'New track')

    def test_rejection_preserves_partial_progress_and_safe_resume(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);count=[0];states=[]
            def approve(proposal):count[0]+=1;return count[0]!=5
            result=publish(files,new_draft(),approve,lambda value:states.append(copy.deepcopy(value)))
            self.assertEqual(result['status'],'rejected');self.assertEqual(len(result['draft']['written']),1);self.assertFalse(list_tracks(files)['tracks'][0]['available'])
            later=[];result=publish(files,result['draft'],lambda proposal:later.append(proposal) or True)
            self.assertEqual(result['status'],'completed');self.assertEqual(len(later),2);self.assertEqual(len(read_track(files,'new_track')['track']['tasks']),1)

    def test_existing_files_and_changed_published_data_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);count=[0]
            def approve(proposal):count[0]+=1;return count[0]!=5
            draft=publish(files,new_draft(),approve)['draft'];target=Path(root)/'agentnik-plans'/'tracks'/'new_track'/'spec.md';target.write_text('user update',encoding='utf-8')
            with self.assertRaises(ValueError):publish(files,draft,lambda _:True)
            self.assertEqual(target.read_text(encoding='utf-8'),'user update')
            other=new_draft()
            with self.assertRaises(ValueError):publish(files,other,lambda _:True)

    def test_target_created_during_approval_stops_without_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);target=Path(root)/'agentnik-plans'/'tracks'/'new_track'/'spec.md'
            def approve(proposal):
                if proposal['path'].endswith('spec.md'):target.write_text('concurrent data',encoding='utf-8')
                return True
            with self.assertRaises(ValueError):publish(files,new_draft(),approve)
            self.assertEqual(target.read_text(encoding='utf-8'),'concurrent data');self.assertFalse(target.with_name('track.json').exists())

    def test_prior_file_changed_during_later_review_stops_publication(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);base=Path(root)/'agentnik-plans'/'tracks'/'new_track';states=[]
            def approve(proposal):
                if proposal['path'].endswith('plan.md'):(base/'spec.md').write_text('external edit',encoding='utf-8')
                return True
            with self.assertRaises(ValueError):publish(files,new_draft(),approve,lambda value:states.append(copy.deepcopy(value)))
            self.assertEqual((base/'spec.md').read_text(encoding='utf-8'),'external edit');self.assertFalse((base/'plan.md').exists());self.assertEqual(len(states[-1]['written']),1)

    def test_rejects_invalid_or_edited_partial_draft(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);draft=new_draft();bad=copy.deepcopy(draft);bad['metadata']['id']='../outside'
            with self.assertRaises(ValueError):validate_draft(bad)
            count=[0]
            def approve(proposal):count[0]+=1;return count[0]!=5
            partial=publish(files,draft,approve)['draft'];partial['spec']='Changed after approval'
            with self.assertRaises(ValueError):publish(files,partial,lambda _:True)

    def test_oversized_metadata_is_rejected_before_creating_directories(self):
        with tempfile.TemporaryDirectory() as root:
            draft=new_draft();draft['metadata']['tasks']=[{'id':'task_'+str(i),'phase':'Phase','step':'Check','status':'pending','evidence':[{'status':'unknown','detail':'한'*500} for _ in range(8)]} for i in range(20)]
            with self.assertRaises(ValueError):publish(ProjectFiles(root),draft,lambda _:True)
            self.assertFalse((Path(root)/'agentnik-plans').exists())

    def test_user_draft_ui_persists_and_rejects_first_change(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QPushButton,QTabWidget,QPlainTextEdit
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from unittest.mock import patch
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def save_draft():
                    dialog=app.activeModalWidget();edit=dialog.findChild(QTabWidget).widget(1);edit.setPlainText('# Requirements\n\nPreserve behavior.\n')
                    next(b for b in dialog.findChildren(QPushButton) if b.text()=='Save draft').click();dialog.reject()
                QTimer.singleShot(0,save_draft);tab.edit_track_draft();saved=store.list_sessions()[0]
                self.assertIn('Preserve behavior',saved['track_draft']['spec']);self.assertFalse((project/'agentnik-plans').exists())
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);tab=window.tabs.currentWidget()
                def open_publish():
                    dialog=app.activeModalWidget()
                    def reject_review():
                        preview=app.activeModalWidget();self.assertIn('Create this directory',preview.findChild(QPlainTextEdit).toPlainText());preview.reject()
                    QTimer.singleShot(0,reject_review);next(b for b in dialog.findChildren(QPushButton) if b.text()=='Review and publish…').click();dialog.reject()
                QTimer.singleShot(0,open_publish);tab.edit_track_draft()
                self.assertFalse((project/'agentnik-plans').exists());self.assertIn('track_draft',store.list_sessions()[0])
            finally:window.close();app.processEvents();store.db.close()

    def test_draft_ui_blocks_configured_credentials(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QPushButton,QTabWidget
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from unittest.mock import patch
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget();window.connections['key-test']={'api_key':'한글"secret'}
                def attempt():
                    dialog=app.activeModalWidget();dialog.findChild(QTabWidget).widget(1).setPlainText('Contains 한글"secret')
                    next(b for b in dialog.findChildren(QPushButton) if b.text()=='Save draft').click();dialog.reject()
                with patch('agentnik.code_ui.QMessageBox.warning') as warning,patch.object(store,'web_backend_specs',return_value=[{'key':'한글"secret'}]):
                    QTimer.singleShot(0,attempt);tab.edit_track_draft();warning.assert_called_once()
                self.assertNotIn('track_draft',store.list_sessions()[0]);self.assertFalse((project/'agentnik-plans').exists())
            finally:window.close();app.processEvents();store.db.close()

    def test_review_callback_cannot_change_approved_proposal(self):
        with tempfile.TemporaryDirectory() as root:
            def approve(proposal):
                if proposal['path'].endswith('spec.md'):proposal['content']='malicious mutation'
                return True
            publish(ProjectFiles(root),new_draft(),approve)
            self.assertNotEqual((Path(root)/'agentnik-plans'/'tracks'/'new_track'/'spec.md').read_text(encoding='utf-8'),'malicious mutation')

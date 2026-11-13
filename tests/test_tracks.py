"""Durable project track validation and read-only view."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles
from agentnik.tracks import list_tracks,read_track,validate_track,read_project_context

FIXTURE=Path(__file__).parent/'fixtures'/'tracks'

class TrackContracts(unittest.TestCase):
    def test_fixture_projection_preserves_task_ids_and_evidence(self):
        files=ProjectFiles(FIXTURE);found=list_tracks(files);self.assertEqual(found['tracks'][0]['id'],'sample_feature')
        data=read_track(files,'sample_feature');self.assertEqual(data['task_ids'],['inspect','implement','verify'])
        self.assertEqual([x['status'] for x in data['projection']['steps']],['completed','in_progress','pending'])
        self.assertEqual(data['track']['tasks'][0]['evidence'][0]['status'],'unknown');self.assertFalse(files.observed)
        self.assertIn('Acceptance criteria',data['spec'])

    def test_invalid_metadata_duplicate_keys_and_legacy_empty_project(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);self.assertEqual(list_tracks(files),{'tracks':[],'incomplete':False})
            target=Path(root)/'agentnik-plans'/'tracks'/'test';target.mkdir(parents=True)
            (target/'track.json').write_text('{"version":1,"version":2}',encoding='utf-8')
            self.assertFalse(list_tracks(files)['tracks'][0]['available'])
            with self.assertRaises(ValueError):read_track(files,'test')
            with self.assertRaises(ValueError):read_track(files,'../escape')

    def test_optional_project_context_is_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            files=ProjectFiles(root);self.assertIsNone(read_project_context(files))
            path=Path(root)/'agentnik-plans'/'context.md';path.parent.mkdir();path.write_text('See README.md and AGENTS.md',encoding='utf-8')
            self.assertEqual(read_project_context(files),'See README.md and AGENTS.md');self.assertFalse(files.observed)
            path.write_text('x'*128001,encoding='utf-8')
            with self.assertRaises(ValueError):read_project_context(files)

    def test_validation_rejects_unknown_versions_duplicate_ids_and_untrusted_evidence(self):
        value=json.loads((FIXTURE/'agentnik-plans'/'tracks'/'sample_feature'/'track.json').read_text(encoding='utf-8-sig'))
        changes=[]
        bad=copy.deepcopy(value);bad['version']=2;changes.append(bad)
        bad=copy.deepcopy(value);bad['tasks'][1]['id']=bad['tasks'][0]['id'];changes.append(bad)
        bad=copy.deepcopy(value);bad['tasks'][0]['status']='invented';changes.append(bad)
        bad=copy.deepcopy(value);bad['tasks'][0]['evidence'][0]['status']='assumed';changes.append(bad)
        bad=copy.deepcopy(value);bad['tasks'][0]['evidence'][0]['status']=[];changes.append(bad)
        bad=copy.deepcopy(value);bad['extra']='unsupported';changes.append(bad)
        for bad in changes:
            with self.subTest(value=str(bad)[:100]),self.assertRaises(ValueError):validate_track(bad)

    def test_viewer_is_read_only_and_does_not_run(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QListWidget,QPlainTextEdit
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'open_request') as request,patch('subprocess.Popen') as process:
            project=Path(root)/'project';shutil.copytree(FIXTURE,project);store=Store(Path(root)/'data');window=Window(store)
            before={p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()}
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def inspect():
                    dialog=app.activeModalWidget();listing=dialog.findChild(QListWidget);listing.setCurrentRow(0);view=dialog.findChild(QPlainTextEdit)
                    self.assertTrue(view.isReadOnly());self.assertIn('Sample feature',view.toPlainText());self.assertIn('not_run',view.toPlainText());dialog.reject()
                request.reset_mock();process.reset_mock();QTimer.singleShot(0,inspect);tab.show_tracks();request.assert_not_called();process.assert_not_called()
                self.assertEqual(before,{p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()})
            finally:window.close();app.processEvents();store.db.close()

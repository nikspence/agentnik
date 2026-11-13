"""Offline selected-track execution and progress contracts."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from agentnik import core
from agentnik.code_agent import CodingRun,ProjectFiles
from agentnik.track_execution import prepare_track,initial_progress,update_progress,projected_plan
from test_code_agent import call
from test_compat_tools import chat
from test_routing import Wire

FIXTURE=Path(__file__).parent/'fixtures'/'tracks'
CONNECTION={'url':'https://gateway.example/v1','protocol':'chat','model':'heavy','stream':False}

class TrackExecution(unittest.TestCase):
    def test_snapshot_budget_credentials_and_progress_validation(self):
        track=prepare_track(ProjectFiles(FIXTURE),'sample_feature')
        with self.assertRaises(ValueError):prepare_track(ProjectFiles(FIXTURE),'sample_feature',context_limit=100)
        with self.assertRaises(ValueError):prepare_track(ProjectFiles(FIXTURE),'sample_feature',secrets=['Sample feature'])
        progress=initial_progress(track)
        updates=[{'id':'implement','status':'completed','detail':'Changed'}, {'id':'verify','status':'in_progress','detail':'Checking'}]
        revised=update_progress(progress,updates)
        self.assertEqual(projected_plan(track,revised)['steps'][2]['status'],'in_progress')
        self.assertEqual(progress['tasks'][1]['status'],'in_progress')
        for bad in ([{'id':'unknown','status':'pending','detail':''}], [updates[0],updates[0]], [{'id':'verify','status':'in_progress','detail':''}]):
            with self.assertRaises(ValueError):update_progress(progress,bad)

    def test_execution_reports_progress_and_blocks_direct_track_changes(self):
        with tempfile.TemporaryDirectory() as root:
            project=Path(root)/'project';shutil.copytree(FIXTURE,project)
            track=prepare_track(ProjectFiles(project),'sample_feature');path=project/'agentnik-plans/tracks/sample_feature/spec.md';before=path.read_bytes()
            updates=[{'id':'implement','status':'completed','detail':'Implemented'}, {'id':'verify','status':'in_progress','detail':'Checking'}]
            calls=[call('report_track_progress',{'updates':json.dumps(updates)}),call('write_file',{'path':'agentnik-plans/tracks/sample_feature/spec.md','content':'changed'},'write')]
            replies=[Wire(chat(calls=calls,finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[]
            def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(CONNECTION,project,'Do the work',selected_track=track).run(events.append)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual([event for event in events if event['kind']=='track_progress'][-1]['progress']['tasks'][2]['status'],'in_progress')
            self.assertIn('Selected project track',json.dumps(bodies[0]))
            names=[tool['function']['name'] for tool in bodies[0]['tools']]
            self.assertIn('report_track_progress',names);self.assertNotIn('update_plan',names)
            self.assertIn('agentnik-plans',json.dumps(bodies[-1]))
            self.assertEqual(events[-1]['status'],'completed')

    def test_changed_source_stops_before_model_request(self):
        with tempfile.TemporaryDirectory() as root:
            project=Path(root)/'project';shutil.copytree(FIXTURE,project);track=prepare_track(ProjectFiles(project),'sample_feature')
            (project/'agentnik-plans/tracks/sample_feature/spec.md').write_text('Changed',encoding='utf-8');events=[]
            with patch.object(core,'open_request') as send:CodingRun(CONNECTION,project,'Work',selected_track=track).run(events.append)
            send.assert_not_called();self.assertIn('changed after review',events[-1]['text'])

    def test_ui_selects_and_runs_track_without_automatic_writes(self):
        import os,time
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QListWidget,QPushButton
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([]);errors=[]
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';shutil.copytree(FIXTURE,project);store=Store(Path(root)/'data');store.config['connections']={'Heavy':dict(CONNECTION)};window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget();combo,model=tab.roles['heavy'];combo.setCurrentIndex(combo.findData('Heavy'));model.setText('heavy');tab.light_enabled.setChecked(False)
                def choose():
                    dialog=app.activeModalWidget()
                    try:
                        dialog.findChild(QListWidget).setCurrentRow(0)
                        next(button for button in dialog.findChildren(QPushButton) if button.text()=='Select for coding runs').click()
                    except Exception as exc:errors.append(repr(exc));dialog.reject()
                with patch.object(core,'open_request') as send:
                    QTimer.singleShot(0,choose);tab.show_tracks();send.assert_not_called()
                self.assertFalse(errors,errors);self.assertEqual(session['selected_track'],'sample_feature')
                path=project/'agentnik-plans/tracks/sample_feature/track.json';before=path.read_bytes();bodies=[]
                spec=project/'agentnik-plans/tracks/sample_feature/spec.md';original=spec.read_bytes()
                def change_during_review(track,connection,prompt):spec.write_text('Changed during review',encoding='utf-8');return True
                with patch.object(tab,'review_selected_track',side_effect=change_during_review),patch.object(core,'open_request') as send,patch('agentnik.code_ui.QMessageBox.warning') as warning:
                    tab.start_coding();send.assert_not_called();self.assertIn('changed after review',str(warning.call_args))
                spec.write_bytes(original)
                def send(connection,url,body,timeout):bodies.append(body);return Wire(chat('Done'),False)
                with patch.object(tab,'review_selected_track',return_value=True),patch.object(core,'open_request',side_effect=send):
                    tab.start_coding();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
                    app.processEvents()
                self.assertIsNone(tab.job);self.assertTrue(bodies);self.assertEqual(session['track_progress']['track_id'],'sample_feature');self.assertEqual(path.read_bytes(),before)
            finally:window.close();app.processEvents();store.db.close()

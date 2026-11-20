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
    def test_saved_project_review_history_is_read_only(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QPlainTextEdit
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';shutil.copytree(FIXTURE,project);store=Store(Path(root)/'data');window=Window(store)
            try:
                files=ProjectFiles(project);track=prepare_track(files,'sample_feature')
                review={'id':'a'*32+'-1','role':'design','model':'legacy','path':'agentnik-plans/tracks/sample_feature/spec.md','source_sha256':'b'*64,'payload_sha256':'c'*64,'evidence':[],'track_context':{'id':track['id'],'digest':track['digest']},'pass_status':'completed','structured':{'status':'valid','findings':[]},'dispositions':{}}
                snapshot={'version':1,'id':'d'*32,'track_id':None,'reviews':[review]}
                sidecar=project/'agentnik-plans/tracks/sample_feature/reviews.json';sidecar.write_text(json.dumps({'version':1,'track_id':'sample_feature','snapshots':[snapshot]}),encoding='utf-8');before=sidecar.read_bytes()
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['coding_review_history']=[snapshot];store.save(session);window.open_session(session);tab=window.tabs.currentWidget();seen=[]
                def inspect(dialog):
                    seen.append(dialog.findChild(QPlainTextEdit,'projectReviewHistory').toPlainText())
                    self.assertIsNone(dialog.findChild(QPushButton,'removeProjectReview'));return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',inspect),patch.object(core,'open_request') as send:
                    tab.show_project_track_reviews('sample_feature');send.assert_not_called()
                self.assertIn('d'*32,seen[0]);self.assertEqual(sidecar.read_bytes(),before);self.assertEqual(session['coding_review_history'],[snapshot])
            finally:window.close();app.processEvents();store.db.close()


    def test_track_review_preview_reports_unresolved_and_source_changes(self):
        import hashlib
        from agentnik.independent_review import track_review_summary
        with tempfile.TemporaryDirectory() as root:
            project=Path(root)/'project';shutil.copytree(FIXTURE,project);files=ProjectFiles(project);track=prepare_track(files,'sample_feature')
            evidence=project/'evidence.txt';evidence.write_text('original',encoding='utf-8');target=project/'agentnik-plans/tracks/sample_feature/spec.md';target_text=files.read('agentnik-plans/tracks/sample_feature/spec.md',remember=False,max_bytes=8000)
            finding={'id':'finding-1','severity':'high','title':'Missing test','rationale':'No criterion','location':'spec.md','assumptions':'','verification':'Ask'}
            review={'id':'a'*32+'-1','role':'design','model':'light','path':'agentnik-plans/tracks/sample_feature/spec.md','source_sha256':hashlib.sha256(target_text.encode()).hexdigest(),'payload_sha256':'b'*64,'evidence':[{'path':'evidence.txt','sha256':hashlib.sha256(b'original').hexdigest(),'payload_sha256':'c'*64}],'track_context':{'id':track['id'],'digest':track['digest']},'pass_status':'completed','structured':{'status':'valid','findings':[finding]},'dispositions':{}}
            history=[{'version':1,'id':'d'*32,'track_id':None,'reviews':[review]}]
            summary=track_review_summary(files,track,history);item=summary['snapshots'][0]['reviews'][0]
            self.assertEqual((item['track_revision_status'],item['source_status']),('matches','matches'));self.assertEqual(item['structured']['findings'][0]['user_disposition']['status'],'unresolved')
            evidence.write_text('changed',encoding='utf-8');self.assertEqual(track_review_summary(files,track,history)['snapshots'][0]['reviews'][0]['source_status'],'stale_or_unavailable')
            evidence.write_text('original',encoding='utf-8');events=[];bodies=[]
            def send_ok(c,url,body,timeout):bodies.append(body);return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send_ok):CodingRun(CONNECTION,project,'Work',selected_track=track).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertNotIn('Missing test',json.dumps(bodies))
            evidence.write_text('changed',encoding='utf-8')
            review['track_context']['digest']='e'*64;self.assertEqual(track_review_summary(files,track,history)['snapshots'][0]['reviews'][0]['track_revision_status'],'changed')
            self.assertEqual(track_review_summary(files,track,[])['snapshots'],[])

    def test_review_overview_reports_recorded_states_without_a_verdict(self):
        from agentnik.independent_review import track_review_overview
        empty=track_review_overview({'snapshots':[]});self.assertEqual(empty['snapshots'],0);self.assertEqual(empty['passes'],0)
        base={'pass_status':'completed','source_status':'matches','track_revision_status':'matches','structured':{'status':'valid','findings':[{'user_disposition':{'status':'unresolved'}},{'user_disposition':{'status':'accepted'}}]}}
        import copy
        failed=dict(base,pass_status='failed',structured={'status':'not_available','findings':[]})
        stale=dict(base,pass_status='stale',source_status='stale_or_unavailable',track_revision_status='changed',structured={'status':'not_available','findings':[]})
        invalid=dict(base,structured={'status':'invalid','findings':[]})
        overview=track_review_overview({'snapshots':[{'reviews':[base,failed,stale,invalid]},{'reviews':[copy.deepcopy(base)]}]})
        self.assertEqual(overview,{'snapshots':2,'passes':5,'completed':3,'incomplete':2,'invalid_output':1,'stale_sources':1,'changed_tracks':1,'unresolved':2})

    def test_track_start_preview_shows_task_and_track_without_review_dependency(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog,QPlainTextEdit
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';shutil.copytree(FIXTURE,project);store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget();track=prepare_track(ProjectFiles(project),'sample_feature');seen=[]
                def accept(dialog):seen.append(dialog.findChild(QPlainTextEdit).toPlainText());return QDialog.DialogCode.Accepted
                def reject(dialog):seen.append(dialog.findChild(QPlainTextEdit).toPlainText());return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',reject),patch.object(core,'open_request') as request:
                    self.assertFalse(tab.review_selected_track(track,CONNECTION,'Task'));request.assert_not_called()
                preview=seen.pop();self.assertIn('User task:\nTask',preview);self.assertIn('Selected track data:',preview);self.assertFalse(tab.job)
                with patch('agentnik.independent_review.track_review_summary',side_effect=ValueError('unavailable')),patch.object(QDialog,'exec',accept):
                    self.assertTrue(tab.review_selected_track(track,CONNECTION,'Task'))
            finally:window.close();app.processEvents();store.db.close()

    def test_independent_review_records_track_context_and_detects_change(self):
        from agentnik.independent_review import track_context_matches,validate_track_context
        with tempfile.TemporaryDirectory() as root:
            project=Path(root)/'project';shutil.copytree(FIXTURE,project);files=ProjectFiles(project);track=prepare_track(files,'sample_feature')
            context={'id':track['id'],'digest':track['digest']};self.assertTrue(track_context_matches(files,context));self.assertIsNone(track_context_matches(files,None))
            for value in ({'id':'../bad','digest':'a'*64},{'id':'sample_feature','digest':'bad'}):
                with self.assertRaises(ValueError):validate_track_context(value)
            plan=project/'agentnik-plans/tracks/sample_feature/plan.md';plan.write_text(plan.read_text(encoding='utf-8')+'\nchanged',encoding='utf-8')
            self.assertFalse(track_context_matches(files,context))

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
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget();combo,model=tab.roles['heavy'];combo.setCurrentIndex(combo.findData('Heavy'));model.setText('heavy')
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
                legacy_reviews=path.parent/'reviews.json';legacy_reviews.write_text('legacy unreadable review data',encoding='utf-8')
                def send(connection,url,body,timeout):bodies.append(body);return Wire(chat('Done'),False)
                with patch.object(tab,'review_selected_track',return_value=True),patch.object(core,'open_request',side_effect=send):
                    tab.start_coding();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
                    app.processEvents()
                self.assertIsNone(tab.job);self.assertTrue(bodies);self.assertEqual(session['track_progress']['track_id'],'sample_feature');self.assertEqual(path.read_bytes(),before)
                self.assertEqual(legacy_reviews.read_text(encoding='utf-8'),'legacy unreadable review data')
            finally:window.close();app.processEvents();store.db.close()

"""Offscreen Agentnik-owned coding UI and role selection, with mock models."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
from agentnik import core
from agentnik.storage import Store
from test_routing import Wire
from test_compat_tools import chat
from test_code_agent import C,call

class CodingWorkspace(unittest.TestCase):
    def test_steering_drafts_are_independent_and_not_sent_on_reopen(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);first=window.repositories.session(ident);second=window.repositories.session(ident);store.save(first);store.save(second)
                window.open_session(first);first_tab=window.tabs.currentWidget();first_tab.steering_input.setText('First draft')
                window.open_session(second);second_tab=window.tabs.currentWidget();second_tab.steering_input.setText('Second draft')
                saved={row['id']:row for row in store.list_sessions()};self.assertEqual(saved[first['id']]['coding_steering_draft'],'First draft');self.assertEqual(saved[second['id']]['coding_steering_draft'],'Second draft')
                window.close_tab(window.tabs.indexOf(first_tab))
                with patch.object(core,'open_request') as request:window.open_session(saved[first['id']]);request.assert_not_called()
                self.assertEqual(window.tabs.currentWidget().steering_input.text(),'First draft');self.assertEqual(second_tab.steering_input.text(),'Second draft')
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_late_approval_event_is_cleared_after_steering_invalidation(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                run=CodingRun(dict(C,stream=False),str(project),'task');tab.job=run;tab.run_id=run.run_id
                proposal={'operation':'run_shell','cwd':str(project),'path':'.','command':'echo test','shell':'shell','environment_keys':[],'max_seconds':10,'max_output_bytes':100}
                tab.steering_input.setText('Change direction');tab.send_steering()
                tab.receive({'run_id':run.run_id,'kind':'operation_proposal','fingerprint':'pending','proposal':proposal});self.assertEqual(tab.pending_fingerprint,'pending')
                tab.receive({'run_id':run.run_id,'kind':'approval_invalidated','fingerprint':'pending'});self.assertIsNone(tab.pending_fingerprint);self.assertTrue(tab.approval_panel.isHidden())
            finally:
                tab.job=None
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_long_steering_activity_is_preserved_in_bounded_entries(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                message='x'*6000;prefix='Steering delivered: ';tab.record_steering(prefix,message)
                saved=next(row for row in store.list_sessions() if row['id']==session['id']);parts=[item['text'][len(prefix):] for item in saved['code_activity'] if item['kind']=='steering']
                self.assertEqual(''.join(parts),message);self.assertTrue(all(len(item['text'])<=2048 for item in saved['code_activity']))
                session['coding_goal']={'objective':'Goal','status':'paused','detail':''};tab.record_steering('Steering delivery uncertain: ','uncertain instruction')
                tab.capture_goal_resume();self.assertIn('x'*100,session['coding_resume']['evidence']);self.assertNotIn('uncertain instruction',session['coding_resume']['evidence'])
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_continuation_keeps_delivered_steering_independent_of_display_language(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                session['coding_goal']={'objective':'Goal','status':'paused','detail':''}
                tab.record_steering('Translated delivery: ','Correction one',delivered=True);tab.record_steering('Steering delivered: ','Legacy correction')
                tab.record_steering('Steering delivery uncertain: ','Uncertain correction');tab.capture_goal_resume()
                evidence=session['coding_resume']['evidence'];self.assertIn('Correction one',evidence);self.assertIn('Legacy correction',evidence);self.assertNotIn('Uncertain correction',evidence)
                saved=next(row for row in store.list_sessions() if row['id']==session['id']);self.assertTrue(any(item['kind']=='steering_delivered' for item in saved['code_activity']))
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_interrupted_goal_reopens_without_running_and_can_continue(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident)
                session.update(code_state='awaiting_approval',coding_goal={'objective':'Original goal','status':'active','detail':'Work started'},coding_last_run_goal=True,coding_resume={'task':'Original goal','evidence':'Earlier result'},draft='Draft next task')
                session['code_activity']=[{'kind':'started','text':'Original run'},{'kind':'steering_delivered','text':'Translated prefix: Retained correction'},{'kind':'steering','text':'Steering delivery uncertain: Do not replay'}]
                store.save(session)
                with patch.object(core,'open_request') as send:window.open_session(session);send.assert_not_called()
                tab=window.tabs.currentWidget();self.assertEqual(session['code_state'],'interrupted');self.assertEqual(session['coding_goal']['status'],'interrupted');self.assertIn('Interrupted',tab.goal_status_label.text());self.assertIn('Original goal',tab.goal_status_label.text())
                self.assertTrue(tab.continue_button.isEnabled());self.assertEqual(tab.composer.toPlainText(),'Draft next task')
                with patch.object(tab,'start_coding') as start:tab.continue_coding();start.assert_called_once_with(True)
                self.assertIn('Earlier result',session['coding_resume']['evidence']);self.assertIn('uncertain actions',session['coding_resume']['evidence'])
                self.assertIn('Retained correction',session['coding_resume']['evidence']);self.assertNotIn('Do not replay',session['coding_resume']['evidence'])
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_failed_goal_can_be_explicitly_continued_after_reopen(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident)
                session.update(code_state='failed',coding_goal={'objective':'Original objective','status':'failed','detail':'Connection interrupted'},coding_last_run_goal=True,coding_resume={'task':'Original objective','evidence':'Earlier evidence'},draft='Unsent draft')
                store.save(session)
                with patch.object(core,'open_request') as request:window.open_session(session);request.assert_not_called()
                tab=window.tabs.currentWidget();self.assertTrue(tab.continue_button.isEnabled());self.assertTrue(tab.goal_enabled.isChecked())
                self.assertIn('Failed',tab.goal_status_label.text());self.assertEqual(tab.composer.toPlainText(),'Unsent draft')
                with patch.object(tab,'start_coding') as start:tab.continue_coding();start.assert_called_once_with(True)
                self.assertEqual(session['coding_resume']['task'],'Original objective');self.assertIn('Earlier evidence',session['coding_resume']['evidence'])
                self.assertIn('Connection interrupted',session['coding_resume']['evidence']);self.assertIn('uncertain actions',session['coding_resume']['evidence'])
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_goal_pause_and_resume_preserve_objective_and_draft(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        def settle(predicate):
            deadline=time.monotonic()+5
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');store.config['connections']={'Main':dict(C,stream=False)};window=Window(store)
            started=threading.Event();release=threading.Event();bodies=[]
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Main'));tab.composer.setPlainText('The original goal');tab.goal_enabled.setChecked(True)
                def delayed(connection,url,body,timeout):started.set();release.wait(5);return Wire(chat('Late'),False)
                with patch.object(core,'open_request',side_effect=delayed):
                    tab.start_coding();settle(started.is_set);self.assertTrue(tab.goal_checkpoint_timer.isActive());tab.checkpoint_goal_progress()
                    saved=next(row for row in store.list_sessions() if row['id']==session['id']);self.assertGreater(saved['coding_goal_progress']['seconds'],0)
                    tab.steering_input.setText('Queued correction');tab.send_steering()
                    tab.composer.setPlainText('Unsent next task');tab.steering_input.setText('Unsent steering');tab.pause_goal();self.assertIsNone(tab.job);self.assertFalse(tab.goal_checkpoint_timer.isActive());release.set();tab.worker.join(5);app.processEvents()
                self.assertEqual(session['code_state'],'paused');self.assertEqual(session['coding_goal']['status'],'paused');self.assertTrue(tab.continue_button.isEnabled());self.assertIn('Paused',tab.goal_status_label.text())
                self.assertIn('Steering not delivered: Queued correction',json.dumps(session['code_activity']));self.assertNotIn('Queued correction',session['coding_resume']['evidence'])
                saved=next(row for row in store.list_sessions() if row['id']==session['id']);window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);tab=window.tabs.currentWidget()
                self.assertTrue(tab.continue_button.isEnabled());self.assertEqual(tab.composer.toPlainText(),'Unsent next task');self.assertEqual(tab.steering_input.text(),'Unsent steering')
                tab.session['coding_goal_progress']={'steps':3,'seconds':999};tab.session['coding_goal_limits']={'steps':1,'seconds':10};store.save(tab.session)
                replies=[Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Checked result'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                def answer(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=answer):tab.continue_coding();settle(lambda:tab.job is None)
                self.assertIn('The original goal',json.dumps(bodies[0]));self.assertNotIn('Unsent next task',json.dumps(bodies[0]));self.assertNotIn('Unsent steering',json.dumps(bodies[0]));self.assertEqual(tab.composer.toPlainText(),'Unsent next task');self.assertEqual(tab.steering_input.text(),'Unsent steering')
                self.assertEqual(tab.session['coding_goal']['status'],'completed');self.assertIn('Completed (model reported)',tab.goal_status_label.text())
                self.assertEqual(tab.session['coding_goal_progress']['steps'],1);self.assertLess(tab.session['coding_goal_progress']['seconds'],10)
            finally:
                release.set()
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_cancel_records_steering_outcomes_in_submission_order(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                run=CodingRun(dict(C,stream=False),str(project),'Task');tab.job=run;tab.run_id=run.run_id
                with run.lock:run.steering_confirmed=['First'];run.steering_inflight=['Second'];run.steering_submitted=True;run.steering=['Third']
                tab.cancel();texts=[item['text'] for item in session['code_activity'] if item['kind'] in ('steering','steering_delivered')]
                self.assertEqual(texts,['Steering delivered: First','Steering delivery uncertain: Second','Steering not delivered: Third'])
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_pause_reports_inflight_steering_as_uncertain(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([]);first=threading.Event();second=threading.Event();release_first=threading.Event();release_second=threading.Event()
        def settle(predicate):
            deadline=time.monotonic()+5
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');store.config['connections']={'Main':dict(C,stream=False)};window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Main'));tab.goal_enabled.setChecked(True);tab.composer.setPlainText('Goal')
                def send(connection,url,body,timeout):
                    if not first.is_set():first.set();release_first.wait(5);return Wire(chat('Step'),False)
                    second.set();release_second.wait(5);return Wire(chat('Late'),False)
                with patch.object(core,'open_request',side_effect=send):
                    tab.start_coding();settle(first.is_set);tab.steering_input.setText('Change direction');tab.send_steering();release_first.set();settle(second.is_set)
                    tab.pause_goal();release_second.set();tab.worker.join(5);app.processEvents()
                self.assertIn('Steering delivery uncertain: Change direction',json.dumps(session['code_activity']))
                self.assertNotIn('Change direction',session['coding_resume']['evidence']);self.assertEqual(session['code_state'],'paused')
            finally:
                release_first.set();release_second.set()
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_goal_step_limit_can_continue_with_same_fresh_limit(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');store.config['connections']={'Main':dict(C,stream=False)};window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['coding_goal_limits']={'steps':1,'seconds':0};store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Main'));tab.goal_enabled.setChecked(True);tab.composer.setPlainText('Original objective')
                replies=[Wire(chat('First step done'),False),Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Finished remaining work'})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[]
                def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                def settle():
                    deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    app.processEvents();self.assertIsNone(tab.job)
                with patch.object(core,'open_request',side_effect=send):
                    tab.start_coding();settle();self.assertEqual(tab.session['code_state'],'limited');self.assertEqual(tab.session['coding_goal_progress']['steps'],1)
                    self.assertTrue(tab.continue_button.isEnabled());tab.composer.setPlainText('Unsent draft');tab.continue_coding();settle()
                self.assertEqual(len(bodies),3);self.assertIn('Original objective',json.dumps(bodies[1]));self.assertIn('First step done',json.dumps(bodies[1]))
                self.assertEqual(tab.session['coding_goal']['status'],'completed');self.assertEqual(tab.session['coding_goal_progress']['steps'],1);self.assertEqual(tab.composer.toPlainText(),'Unsent draft')
                self.assertEqual(tab.session['coding_goal_run_limits'],{'steps':1,'seconds':0});tab.session['coding_goal_limits']={'steps':5,'seconds':30}
                from PySide6.QtWidgets import QDialog,QPlainTextEdit
                captured=[]
                def inspect(dialog):captured.append(dialog.findChild(QPlainTextEdit,'goalDetailsText').toPlainText());return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',inspect):tab.show_goal_details()
                self.assertIn('Completed goal steps: 1 / 1',captured[0]);self.assertNotIn('1 / 5',captured[0])
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_goal_mode_persists_model_reported_completion(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['connections']={'Main':dict(C,stream=False)};window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Main'));tab.composer.setPlainText('Finish the feature');tab.goal_enabled.setChecked(True)
                replies=[Wire(chat('Working'),False),Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Verified result'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                with patch.object(core,'open_request',side_effect=replies):
                    tab.start_coding();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    app.processEvents()
                self.assertIsNone(tab.job);saved=next(row for row in store.list_sessions() if row['id']==session['id'])
                self.assertEqual(saved['coding_goal']['objective'],'Finish the feature');self.assertEqual(saved['coding_goal']['status'],'completed')
                self.assertIn('Verified result',saved['coding_goal']['detail']);self.assertIn('No structured test report',saved['coding_goal']['detail'])
                self.assertIn('model reported',tab.activity.toPlainText())
                from PySide6.QtWidgets import QDialog,QPlainTextEdit
                captured=[]
                def inspect(dialog):captured.append(dialog.findChild(QPlainTextEdit,'goalDetailsText').toPlainText());return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',inspect):tab.show_goal_details()
                self.assertIn('Finish the feature',captured[0]);self.assertIn('Verified result',captured[0]);self.assertIn('Completed goal steps: 2 / Unlimited',captured[0]);self.assertIn('Active goal time (seconds):',captured[0])
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_steering_during_approval_preserves_composer_and_reaches_model(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        app=QApplication.instance() or QApplication([])
        def settle(predicate):
            deadline=time.monotonic()+4
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.composer.setPlainText('Unsent next task');run=CodingRun(dict(C,stream=False,api_key='secret-key'),str(project),'task');bodies=[]
                replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo hello'})],finish='tool_calls'),False),Wire(chat('Adjusted'),False)]
                def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send),patch('agentnik.shell.execute') as execute:
                    tab.launch(run,'Started');settle(lambda:bool(tab.pending_fingerprint))
                    tab.steering_input.setText('Use another approach secret-key');self.assertNotIn('secret-key',json.dumps(session));tab.send_steering();settle(lambda:tab.job is None);execute.assert_not_called()
                self.assertEqual(tab.composer.toPlainText(),'Unsent next task');self.assertIn('Use another approach [redacted]',json.dumps(bodies[-1]))
                self.assertNotIn('secret-key',json.dumps(session));self.assertIn('Steering delivered',tab.activity.toPlainText())
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_single_model_run_preserves_legacy_assignments(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['connections']={'Main':{'url':'https://main.example/v1','protocol':'chat','model':'main'}};window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident)
                session['coding_models']={'heavy':{'connection':'Main','model':'main'},'light':{'connection':'Old','model':'legacy'}}
                session['coding_subagent_model']={'connection':'Other','model':'old-alternate'};store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.composer.setPlainText('Inspect');tab.model_panel.show();app.processEvents()
                self.assertFalse(tab.roles['heavy'][0].isHidden());self.assertEqual(set(tab.roles),{'heavy','decision'})
                from PySide6.QtWidgets import QDialog,QPlainTextEdit,QPushButton
                self.assertIsNotNone(tab.model_panel.findChild(QPushButton,'legacyModelSettings'));captured=[]
                def inspect(dialog):
                    view=dialog.findChild(QPlainTextEdit,'legacyModelSettingsText');self.assertTrue(view.isReadOnly());captured.append(view.toPlainText());return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',inspect),patch.object(core,'open_request') as request:tab.show_legacy_model_settings();request.assert_not_called()
                self.assertIn('legacy',captured[0]);self.assertIn('old-alternate',captured[0])
                with patch.object(tab,'launch') as launch:
                    tab.start_coding();run=launch.call_args.args[0]
                self.assertEqual(run.connection['model'],'main')
                self.assertEqual(session['coding_models']['light']['model'],'legacy');self.assertEqual(session['coding_subagent_model']['model'],'old-alternate')
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_model_binding_migrates_legacy_assignment_without_losing_light(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident)
                session['coding_models']={'heavy':{'connection':'Old','model':'old-model'},'light':{'connection':'Other','model':'old-light'}}
                store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                self.assertEqual(tab.roles['heavy'][1].text(),'old-model')
                self.assertNotIn('model',tab.session['coding_models'])
                tab.save_models();self.assertEqual(tab.session['coding_models']['model'],{'connection':'Old','model':'old-model'})
                self.assertEqual(tab.session['coding_models']['light'],{'connection':'Other','model':'old-light'})
                tab.session['coding_models']['model']={'connection':'New','model':'new-model'};store.save(tab.session)
                window.close_tab(window.tabs.indexOf(tab));window.open_session(session);reopened=window.tabs.currentWidget()
                self.assertEqual(reopened.roles['heavy'][1].text(),'new-model');self.assertIn('unavailable',reopened.roles['heavy'][0].currentText())
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_shell_switch_can_release_a_pending_command(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        app=QApplication.instance() or QApplication([])
        def settle(predicate):
            deadline=time.monotonic()+4
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                self.assertFalse(tab.shell_auto.isChecked());run=CodingRun(dict(C,stream=False),str(project),'task')
                replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo hello'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                with patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute',return_value={'exit_code':0,'output':'ok','truncated':False}) as execute:
                    tab.launch(run,'Started');settle(lambda:bool(tab.pending_fingerprint));execute.assert_not_called()
                    self.assertTrue(tab.shell_auto.isEnabled());tab.shell_auto.setChecked(True)
                    settle(lambda:tab.job is None);execute.assert_called_once()
                self.assertIsNone(tab.pending_fingerprint);self.assertIn('echo hello',tab.activity.toPlainText())
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_response_thinking_preference_and_run_timing_are_saved(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.show_thinking.setChecked(True);run=CodingRun(dict(C,stream=False),str(project),'task')
                def answer(connection,body,runtime,emit,state):
                    state.update(text='Response text',thinking='Thought text',metrics={});return ({'role':'assistant','content':'Response text'},[])
                with patch('agentnik.compat_tools.request',side_effect=answer):
                    tab.launch(run,'Started');deadline=time.monotonic()+4
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    app.processEvents()
                self.assertIsNone(tab.job);saved=next(row for row in store.list_sessions() if row['id']==session['id'])
                activity='\n'.join(item['text'] for item in saved['code_activity'])
                self.assertIn('Started: ',activity);self.assertIn('Ended: ',activity);self.assertIn('Elapsed: ',activity)
                self.assertIn('Thought text',activity);self.assertEqual(activity.count('Response text'),1);self.assertTrue(saved['coding_show_thinking'])
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);self.assertTrue(window.tabs.currentWidget().show_thinking.isChecked())
            finally:
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_cancel_records_inflight_usage_and_ignores_late_events(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            started=threading.Event();release=threading.Event()
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                run=CodingRun(dict(C,stream=False),str(project),'task')
                def delayed(*args,**kwargs):started.set();release.wait(5);return Wire(chat('Late answer'),False)
                with patch.object(core,'open_request',side_effect=delayed):
                    tab.launch(run,'Started');deadline=time.monotonic()+3
                    while not started.is_set() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
                    self.assertTrue(started.is_set(),tab.activity.toPlainText());tab.cancel()
                    self.assertIsNone(tab.job);self.assertEqual(tab.session['code_state'],'cancelled')
                    saved=next(row for row in store.list_sessions() if row['id']==session['id'])
                    self.assertIn('Model: 1 request(s), input unknown, output unknown tokens',saved['code_activity'][-1]['text'])
                    tab.receive({'run_id':run.run_id,'kind':'finished','status':'completed','text':'Late answer','usage':'Usage: fabricated'})
                    release.set();tab.worker.join(3);app.processEvents()
                    self.assertEqual(tab.session['code_state'],'cancelled');self.assertNotIn('Late answer',json.dumps(tab.session))
            finally:
                release.set()
                with patch('agentnik.ui.confirm',return_value=True):window.close()
                app.processEvents();store.db.close()

    def test_activity_follows_bottom_and_respects_scrolled_position(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store);window.resize(800,650)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);window.show();app.processEvents()
                tab=window.tabs.currentWidget()
                for number in range(120):tab.record('output','Activity line '+str(number))
                app.processEvents();scroll=tab.activity.verticalScrollBar();self.assertGreater(scroll.maximum(),0)
                self.assertEqual(scroll.value(),scroll.maximum())
                scroll.setValue(scroll.maximum()//3);app.processEvents();before=scroll.value()
                top=tab.activity.cursorForPosition(QPoint(2,2)).block().text()
                tab.record('output','New line while reading');app.processEvents()
                self.assertEqual(scroll.value(),before);self.assertEqual(tab.activity.cursorForPosition(QPoint(2,2)).block().text(),top)
                scroll.setValue(scroll.maximum());tab.record('output','New line at bottom\nSecond line');app.processEvents()
                self.assertEqual(scroll.value(),scroll.maximum());self.assertIn('Second line',tab.activity.toPlainText())
                saved=next(item for item in store.list_sessions() if item['id']==session['id'])
                self.assertEqual(saved['version'],5);self.assertEqual(len(saved['code_activity']),122)
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents()
                reopened=window.tabs.currentWidget();self.assertIn('Activity line 0',reopened.activity.toPlainText());self.assertIn('Second line',reopened.activity.toPlainText())
                self.assertEqual(reopened.activity.verticalScrollBar().value(),reopened.activity.verticalScrollBar().maximum())
            finally:window.close();app.processEvents();store.db.close()

    def test_activity_retention_preserves_recent_entries_and_legacy_sessions(self):
        from agentnik import sessions
        data={'version':4,'code_activity':[]}
        with patch.object(sessions,'MAX_CODE_ACTIVITY_EVENTS',40),patch.object(sessions,'MAX_CODE_ACTIVITY_CHARS',10000):
            for number in range(60):sessions.append_code_activity(data,'output','Entry '+str(number))
        self.assertEqual(data['version'],5);self.assertLessEqual(len(data['code_activity']),40)
        self.assertEqual(data['code_activity'][-1]['text'],'Entry 59');self.assertNotEqual(data['code_activity'][0]['text'],'Entry 0')

    def test_activity_retention_keeps_view_on_same_text_when_trimmed(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication
        from agentnik import sessions
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(sessions,'MAX_CODE_ACTIVITY_EVENTS',40):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store);window.resize(800,650)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);window.show();app.processEvents();tab=window.tabs.currentWidget()
                for number in range(40):tab.record('output','Line '+str(number)+' '+('long text '*25))
                app.processEvents();scroll=tab.activity.verticalScrollBar();scroll.setValue(scroll.maximum()*3//4);app.processEvents()
                top=tab.activity.cursorForPosition(QPoint(2,2)).block().text();tab.record('output','Additional activity');app.processEvents()
                self.assertEqual(tab.activity.cursorForPosition(QPoint(2,2)).block().text(),top)
            finally:window.close();app.processEvents();store.db.close()

    def test_skill_selection_pins_version_and_requires_review_after_change(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QCheckBox,QMessageBox
        from agentnik.ui import Window
        from agentnik.code_agent import ProjectFiles
        from agentnik.project_skills import read_skill
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';skill=project/'.agents/skills/review';skill.mkdir(parents=True)
            path=skill/'SKILL.md';path.write_text('---\nname: review\ndescription: Review\n---\nOriginal.',encoding='utf-8')
            store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def select_and_accept():
                    dialog=app.activeModalWidget()
                    next(check for check in dialog.findChildren(QCheckBox) if check.text().startswith('review [repository]')).setChecked(True)
                    dialog.accept()
                QTimer.singleShot(0,select_and_accept);tab.choose_skills()
                original=read_skill(ProjectFiles(project),'review')['sha256'];self.assertEqual(tab.session['coding_skill_pins'],{'review':original})
                def update_during_selection():
                    dialog=app.activeModalWidget()
                    path.write_text('---\nname: review\ndescription: Review\n---\nChanged during selection.',encoding='utf-8')
                    dialog.accept()
                with patch.object(QMessageBox,'warning') as warning:
                    QTimer.singleShot(0,update_during_selection);tab.choose_skills()
                    warning.assert_called_once()
                self.assertEqual(tab.session['coding_skill_pins'],{'review':original})
                path.write_text('---\nname: review\ndescription: Review\n---\nChanged.',encoding='utf-8')
                with patch.object(QMessageBox,'warning') as warning,patch.object(tab,'launch') as launch:
                    tab.start_coding();warning.assert_called_once();launch.assert_not_called()
                    self.assertIn('changed',warning.call_args.args[2])
                QTimer.singleShot(0,select_and_accept);tab.choose_skills()
                self.assertNotEqual(tab.session['coding_skill_pins']['review'],original)
            finally:window.close();app.processEvents();store.db.close()

    def test_mcp_selections_restore_and_changed_servers_require_reselection(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QCheckBox,QMessageBox
        from agentnik.ui import Window
        from agentnik.sessions import validate_session
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['mcp_servers']=[{'name':'Local','command':'never-start','args':[],'enabled':True},{'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'private-reference','enabled':True}]
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.mcp_choice.setCurrentIndex(1)
                def select_extra():
                    dialog=app.activeModalWidget();next(check for check in dialog.findChildren(QCheckBox) if check.text().startswith('Remote')).setChecked(True);dialog.accept()
                QTimer.singleShot(0,select_extra);tab.choose_additional_mcp()
                saved=next(item for item in store.list_sessions() if item['id']==session['id']);validate_session(saved)
                self.assertNotIn('private-reference',json.dumps(saved['coding_mcp_selection']))
                import copy
                invalid=copy.deepcopy(saved);invalid['coding_mcp_selection']['extra'].append(dict(invalid['coding_mcp_selection']['primary']))
                with self.assertRaises(ValueError):validate_session(invalid)
                invalid=copy.deepcopy(saved);invalid['coding_mcp_selection']['primary']['sha256']='bad'
                with self.assertRaises(ValueError):validate_session(invalid)
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);tab=window.tabs.currentWidget()
                self.assertEqual(tab.mcp_choice.currentData(),'Local');self.assertEqual(tab.mcp_extra,['Remote'])
                store.config['mcp_servers'][0]['command']='replacement';tab.refresh_mcp_servers()
                self.assertIn('changed or unavailable',tab.mcp_choice.currentText())
                tab.composer.setPlainText('task')
                with patch.object(tab,'role_connection',return_value={'model':'test','url':'http://localhost'}),patch.object(QMessageBox,'warning') as warning,patch.object(tab,'launch') as launch:
                    tab.start_coding();warning.assert_called_once();launch.assert_not_called();self.assertIn('changed or is unavailable',warning.call_args.args[2])
                tab.mcp_choice.setCurrentIndex(tab.mcp_choice.findData('Local'))
                self.assertEqual(tab.mcp_choice.currentData(),'Local')
                store.config['mcp_servers'][1]['enabled']=False
                with patch.object(tab,'role_connection',return_value={'model':'test','url':'http://localhost'}),patch.object(QMessageBox,'warning') as warning,patch.object(tab,'launch') as launch:
                    tab.start_coding();warning.assert_called_once();launch.assert_not_called()
                def remove_unavailable():
                    dialog=app.activeModalWidget();next(check for check in dialog.findChildren(QCheckBox) if check.text().startswith('Remote')).setChecked(False);dialog.accept()
                QTimer.singleShot(0,remove_unavailable);tab.choose_additional_mcp();self.assertEqual(tab.mcp_extra,[])
            finally:window.close();app.processEvents();store.db.close()

    def test_local_mcp_selection_and_approval_preview(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QCheckBox
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['mcp_servers']=[{'name':'Database','command':'npx','args':['-y','server','run'],'enabled':True},{'name':'Disabled','command':'server','args':[],'enabled':False},{'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}]
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                self.assertEqual(tab.mcp_choice.count(),3);self.assertIsNone(tab.mcp_choice.currentData());self.assertEqual(tab.mcp_choice.itemData(1),'Database');self.assertEqual(tab.mcp_choice.itemData(2),'Remote')
                tab.mcp_choice.setCurrentIndex(1)
                def choose_extra():
                    dialog=app.activeModalWidget();next(check for check in dialog.findChildren(QCheckBox) if check.text().startswith('Remote')).setChecked(True);dialog.accept()
                QTimer.singleShot(0,choose_extra);tab.choose_additional_mcp();self.assertEqual(tab.mcp_extra,['Remote']);self.assertIn('(1)',tab.mcp_extra_button.text())
                tab.job=MagicMock();tab.run_id='mcp-run'
                start={'operation':'mcp_start','server':'Database','command':'npx','arguments':['-y','server','run'],'working_directory':'D:/mcp-work'}
                tab.receive({'run_id':'mcp-run','kind':'operation_proposal','fingerprint':'start','proposal':start})
                self.assertIn('START LOCAL MCP SERVER',tab.approval.toPlainText());self.assertIn('npx',tab.approval.toPlainText());self.assertIn('D:/mcp-work',tab.approval.toPlainText());self.assertIn('including writes and data access',tab.approval.toPlainText());self.assertFalse(tab.approve_mcp_run.isHidden());tab.decide(True,'mcp_server_run');tab.job.decide.assert_called_with('start',True,'mcp_server_run')
                proposal={'operation':'mcp_call','server':'Database','command':'npx','server_arguments':['-y','server','run'],'tool':'query','description':'Read data','schema':{'type':'object'},'output_schema':{'type':'object','required':['rows']},'annotations':{'readOnlyHint':True},'arguments':{'sql':'SELECT 1'}}
                tab.receive({'run_id':'mcp-run','kind':'operation_proposal','fingerprint':'call','proposal':proposal})
                for value in ('MCP TOOL CALL','Database','query','Read data','SELECT 1','readOnlyHint','untrusted','Output schema','rows'):self.assertIn(value,tab.approval.toPlainText())
                tab.decide(False)
                remote={'operation':'mcp_connect','server':'Remote','url':'https://example.com/mcp'}
                tab.receive({'run_id':'mcp-run','kind':'operation_proposal','fingerprint':'remote','proposal':remote})
                self.assertIn('CONNECT TO REMOTE',tab.approval.toPlainText());self.assertIn(remote['url'],tab.approval.toPlainText());tab.decide(False)
                proposal.update(operation='mcp_call_remote',url='https://example.com/mcp')
                tab.receive({'run_id':'mcp-run','kind':'operation_proposal','fingerprint':'remote-call','proposal':proposal})
                self.assertIn('REMOTE MCP TOOL CALL',tab.approval.toPlainText());self.assertIn('SELECT 1',tab.approval.toPlainText());self.assertIn('Output schema',tab.approval.toPlainText());tab.decide(False)
                resource={'operation':'mcp_read_resource','server':'Database','command':'npx','server_arguments':['-y','server','run'],'resource':{'uri':'test://record','name':'Record','description':'Test','mimeType':'text/plain'}}
                tab.receive({'run_id':'mcp-run','kind':'operation_proposal','fingerprint':'resource','proposal':resource})
                self.assertIn('MCP RESOURCE REQUEST',tab.approval.toPlainText());self.assertIn('test://record',tab.approval.toPlainText());tab.decide(False)
                resource.pop('command');resource.pop('server_arguments');resource['url']='https://example.com/mcp'
                tab.receive({'run_id':'mcp-run','kind':'operation_proposal','fingerprint':'remote-resource','proposal':resource})
                self.assertIn(resource['url'],tab.approval.toPlainText());self.assertIn('test://record',tab.approval.toPlainText());tab.decide(False)
                prompt={'operation':'mcp_get_prompt','server':'Remote','url':'https://example.com/mcp','prompt':{'name':'review','description':'Review','arguments':[]},'arguments':{'code':'sample'}}
                tab.receive({'run_id':'mcp-run','kind':'operation_proposal','fingerprint':'prompt','proposal':prompt})
                for value in ('MCP PROMPT REQUEST','https://example.com/mcp','review','sample'):self.assertIn(value,tab.approval.toPlainText())
                tab.decide(False)
                template={'operation':'mcp_read_resource_template','server':'Remote','url':'https://example.com/mcp','template':{'name':'Item','uriTemplate':'test://item/{id}'},'variables':{'id':'a/b'},'uri':'test://item/a%2Fb'}
                tab.receive({'run_id':'mcp-run','kind':'operation_proposal','fingerprint':'template','proposal':template})
                for value in ('MCP RESOURCE TEMPLATE REQUEST','test://item/{id}','a%2Fb'):self.assertIn(value,tab.approval.toPlainText())
                tab.decide(False)
                tab.job=None;tab.run_id=None
            finally:window.close();app.processEvents();store.db.close()

    def test_structured_test_approval_keeps_shell_review_and_test_format(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.job=MagicMock();tab.run_id='test-run';tab.advice_connection=None
                proposal={'operation':'run_shell','purpose':'tests','test_format':'unittest','cwd':str(project),'path':'.','command':'python -m unittest','shell':'powershell.exe','environment_keys':['PATH'],'max_seconds':45,'max_output_bytes':32000}
                tab.receive({'run_id':'test-run','kind':'operation_proposal','fingerprint':'test-proposal','proposal':proposal})
                self.assertIn('TEST RUN',tab.approval.toPlainText());self.assertIn('unittest',tab.approval.toPlainText());self.assertIn('python -m unittest',tab.approval.toPlainText());self.assertTrue(tab.approve.isEnabled());self.assertTrue(tab.approve_mcp_run.isHidden())
                tab.decide(False);self.assertTrue(tab.approval_panel.isHidden());tab.job=None;tab.run_id=None
            finally:window.close();app.processEvents();store.db.close()

    def test_git_approval_previews_show_only_while_pending(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.job=MagicMock();tab.run_id='git-run'
                for operation,label in [('git_stage','STAGE FILES'),('git_unstage','UNSTAGE FILES'),('git_create_branch','CREATE BRANCH'),('git_commit_staged','GIT COMMIT'),('git_fetch_connect','CONNECT TO GIT REMOTE'),('git_fetch','FETCH GIT BRANCH'),('git_push_connect','CONNECT TO GIT PUSH DESTINATION'),('git_push','PUSH GIT BRANCH')]:
                    proposal={'operation':operation,'cwd':str(project),'path':'one.txt','paths':['one.txt'],'diff':'-old\n+new\n','head':'a'*40,'name':'feature/review','identity':'Test <test@example.invalid>','message':'Reviewed snapshot','remote':'origin','branch':'main','local_branch':'main','url':'https://example.invalid/repo','commit':'a'*40,'target':'refs/remotes/origin/main','previous':''}
                    tab.receive({'run_id':'git-run','kind':'operation_proposal','fingerprint':operation,'proposal':proposal})
                    self.assertFalse(tab.approval_panel.isHidden());self.assertIn(label,tab.approval.toPlainText())
                    self.assertEqual(tab.diff.isHidden(),operation in ('git_create_branch','git_fetch_connect','git_fetch','git_push_connect','git_push'));self.assertTrue(tab.advice_label.isHidden())
                    if operation=='git_fetch':self.assertIn('a'*40,tab.approval.toPlainText());self.assertIn('refs/remotes/origin/main',tab.approval.toPlainText())
                    if operation=='git_push_connect':
                        self.assertFalse(tab.git_auth_row.isHidden());tab.git_username.setText('git-user')
                        with patch('agentnik.git_credentials.load_token',return_value='secret-token') as load:
                            tab.git_load_token.click();load.assert_called_once_with('https://example.invalid/repo','git-user')
                        with patch('agentnik.git_credentials.delete_token') as delete,patch('agentnik.code_ui.QMessageBox.information'):
                            tab.git_forget_token.click();delete.assert_called_once_with('https://example.invalid/repo','git-user');self.assertEqual(tab.git_token.text(),'')
                        tab.git_token.setText('secret-token')
                        tab.git_remember_token.setChecked(True)
                        with patch('agentnik.git_credentials.save_token') as save:
                            tab.decide(True);save.assert_called_once_with('https://example.invalid/repo','git-user','secret-token')
                        self.assertEqual(tab.job.decide.call_args.kwargs['git_credentials'],('git-user','secret-token'));self.assertEqual(tab.git_token.text(),'');self.assertNotIn('secret-token',json.dumps(tab.session))
                    elif operation=='git_fetch_connect':
                        tab.job.decide.reset_mock();tab.git_username.setText('git-user');tab.git_token.setText('secret-token');tab.git_remember_token.setChecked(True)
                        with patch('agentnik.git_credentials.save_token',side_effect=RuntimeError('private')),patch('agentnik.code_ui.QMessageBox.warning') as warning:
                            tab.decide(True);warning.assert_called_once();tab.job.decide.assert_not_called()
                        self.assertFalse(tab.approval_panel.isHidden());self.assertNotIn('private',str(warning.call_args));tab.decide(False)
                    else:tab.decide(False)
                    self.assertTrue(tab.approval_panel.isHidden())
                tab.job=None;tab.run_id=None
            finally:window.close();app.processEvents();store.db.close()

    def test_advice_does_not_send_decision_credential_in_command(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.job=MagicMock();tab.run_id='run';tab.advice_connection={'url':'https://example.com','model':'safety','api_key':'decision-secret'};tab.advice_destination='Example / safety'
                proposal={'operation':'run_shell','cwd':str(project),'path':'.','command':'echo decision-secret','shell':'powershell.exe','environment_keys':['PATH'],'max_seconds':45,'max_output_bytes':32000}
                with patch('agentnik.decision_advice.request') as request:
                    tab.receive({'run_id':'run','kind':'operation_proposal','fingerprint':'one','proposal':proposal});request.assert_not_called()
                self.assertIn('UNKNOWN',tab.advice_label.text());self.assertIn('no request was made',tab.advice_label.text());self.assertTrue(tab.approve.isEnabled())
                self.assertNotIn('decision-secret',json.dumps(store.list_sessions()))
                tab.job=None;tab.run_id=None
            finally:window.close();app.processEvents();store.db.close()

    def test_advice_failure_is_unknown_and_late_result_is_ignored(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        def settle(predicate):
            deadline=time.monotonic()+4
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            release=threading.Event();started=threading.Event()
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.job=MagicMock();tab.run_id='run';tab.advice_connection={'url':'https://example.com','model':'safety','api_key':'secret'};tab.advice_destination='Example / safety'
                proposal={'operation':'run_shell','cwd':str(project),'path':'.','command':'echo test','shell':'powershell.exe','environment_keys':['PATH'],'max_seconds':45,'max_output_bytes':32000}
                with patch('agentnik.decision_advice.request',side_effect=ValueError('private error')):
                    tab.receive({'run_id':'run','kind':'operation_proposal','fingerprint':'one','proposal':proposal});settle(lambda:tab.advice_job is None)
                self.assertIn('UNKNOWN',tab.advice_label.text());self.assertTrue(tab.approve.isEnabled());self.assertNotIn('private error',json.dumps(tab.session))
                def delayed(*args):started.set();release.wait(3);return {'answers':{'risk':{'choice':'safe'}}}
                with patch('agentnik.decision_advice.request',side_effect=delayed):
                    tab.receive({'run_id':'run','kind':'operation_proposal','fingerprint':'two','proposal':proposal});settle(started.is_set)
                    tab.cancel();release.set()
                    for _ in range(20):app.processEvents();time.sleep(.005)
                self.assertIsNone(tab.job);self.assertNotIn('advice SAFE',json.dumps(tab.session))
            finally:release.set();window.close();app.processEvents();store.db.close()

    def test_enabled_decision_advice_waits_for_review_and_never_approves(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        def settle(predicate):
            deadline=time.monotonic()+4
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['connections']={'Heavy':{'url':'https://gateway.example/v1','protocol':'chat','model':'coder','stream':False},'Decision':{'url':'https://decision.example/v1','protocol':'chat','model':'safety','api_key':'decision-secret'}}
            window=Window(store);started=threading.Event();release=threading.Event();seen=[]
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                for role,name in [('heavy','Heavy'),('decision','Decision')]:tab.roles[role][0].setCurrentIndex(tab.roles[role][0].findData(name))
                self.assertFalse(tab.advice_enabled.isChecked());tab.advice_enabled.setChecked(True);tab.composer.setPlainText('Run a command')
                replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo hello'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                def advice(connection,proposal,cancel):
                    seen.append((connection,proposal));started.set();release.wait(3)
                    return {'answers':{'risk':{'choice':'danger','confidence':.9}}}
                with patch.object(core,'open_request',side_effect=replies),patch('agentnik.decision_advice.request',side_effect=advice),patch('agentnik.shell.execute',return_value={'exit_code':0,'output':'ok','truncated':False}) as execute:
                    tab.start_coding();settle(started.is_set)
                    self.assertFalse(tab.approve.isEnabled());self.assertFalse(tab.reject.isEnabled());self.assertTrue(tab.cancel_button.isEnabled())
                    tab.decide(True);execute.assert_not_called()
                    self.assertEqual(seen[0][0]['model'],'safety');self.assertEqual(seen[0][1]['command'],'echo hello')
                    release.set();settle(lambda:tab.approve.isEnabled())
                    self.assertIn('DANGER',tab.advice_label.text());self.assertIn('decision.example',tab.advice_label.text());execute.assert_not_called()
                    tab.decide(True);settle(lambda:tab.job is None);execute.assert_called_once()
                saved=store.list_sessions()[0];self.assertTrue(saved['coding_advice_enabled']);self.assertNotIn('decision-secret',json.dumps(saved))
            finally:release.set();window.close();app.processEvents();store.db.close()

    def test_shell_and_delete_approval_display_scope_and_diff(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();tab.job=MagicMock();tab.run_id='run';window.show();app.processEvents()
                proposal={'operation':'run_shell','cwd':str(project),'path':'.','command':'echo test','shell':'powershell.exe','environment_keys':['PATH'],'max_seconds':45,'max_output_bytes':32000}
                with patch('agentnik.decision_advice.request') as request:
                    tab.receive({'run_id':'run','kind':'operation_proposal','fingerprint':'one','proposal':proposal});request.assert_not_called()
                self.assertIn('echo test',tab.approval.toPlainText());self.assertIn('network',tab.approval.toPlainText());self.assertIn('not sandboxed',tab.approval.toPlainText());self.assertFalse(tab.diff.isVisible())
                self.assertIn('NOT CHECKED',tab.advice_label.text());self.assertTrue(tab.approve.isEnabled())
                tab.show_advice({'answers':{'risk':{'choice':'danger','confidence':.9}}},'stale')
                self.assertIn('NOT CHECKED',tab.advice_label.text())
                tab.show_advice({'answers':{'risk':{'choice':'danger','confidence':.9}}},'one')
                self.assertIn('DANGER',tab.advice_label.text());self.assertIn('90%',tab.advice_label.text());self.assertTrue(tab.approve.isEnabled())
                tab.job.decide.return_value=True;tab.decide(False)
                tab.receive({'run_id':'run','kind':'operation_proposal','fingerprint':'two','proposal':{'operation':'delete_file','cwd':str(project),'path':'old.txt','diff':'-old text'}})
                self.assertIn('DELETE FILE',tab.approval.toPlainText());self.assertIn('-old text',tab.diff.toPlainText());self.assertTrue(tab.diff.isVisible())
                tab.job=None;tab.run_id=None
            finally:window.close();app.processEvents();store.db.close()

    def test_search_settings_and_strict_navigation_policy(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik import routing
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            connection={'url':'https://gateway.example/v1','protocol':'chat','model':'heavy','stream':False}
            store.config['connections']={'Gateway':connection};routing.save_defaults(store.config,'Gateway',connection,'Agentnik only','strict_public')
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Gateway'))
                with patch('agentnik.code_ui.SearchBackends') as dialog:
                    tab.search_settings.click();dialog.assert_called_once_with(tab,store);dialog.return_value.exec.assert_called_once()
                tab.composer.setPlainText('Research API');tab.web_enabled.setChecked(True)
                with patch('agentnik.code_ui.CodingRun') as run,patch.object(tab,'launch'):
                    tab.start_coding();self.assertEqual(run.call_args.kwargs['search_provider'],'none')
                    self.assertTrue(run.call_args.kwargs['web_enabled'])
                    routing.save_defaults(store.config,'Gateway',connection,'Agentnik only','public_fetch')
                    with patch.object(store,'web_backend_specs',return_value=[{'id':'ollama-search','kind':'ollama','key':'secret'}]):
                        tab.start_coding();self.assertEqual(run.call_args.kwargs['search_provider'],'managed');self.assertEqual(run.call_args.kwargs['web_backends'],[])
                    with patch.object(store,'web_backend_specs',return_value=[{'id':'brave','kind':'brave','key':'brave-test-key'},{'id':'ollama','kind':'ollama','key':'ollama-test-key'}]):
                        tab.start_coding();self.assertEqual(run.call_args.kwargs['search_provider'],'managed');self.assertEqual([b['kind'] for b in run.call_args.kwargs['web_backends']],['brave'])
                    tab.roles['heavy'][0].addItem('Ollama direct','Ollama direct');window.connections['Ollama direct']={'url':'https://ollama.com','protocol':'chat','model':'cloud'}
                    tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Ollama direct'))
                    with patch.object(store,'web_backend_specs',return_value=[{'id':'ollama-search','kind':'ollama','key':'secret'}]):
                        tab.start_coding();self.assertEqual(run.call_args.kwargs['search_provider'],'managed')
                self.assertIsNone(tab.job)
            finally:window.close();app.processEvents();store.db.close()

    def test_research_sources_are_saved_and_opened_only_on_request(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_ui import CodingSourcesDialog
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();tab.job=object();tab.run_id='run'
                tab.receive({'run_id':'run','kind':'source','source':{'id':'S1','title':'API docs','url':'https://example.com/docs'}})
                tab.receive({'run_id':'run','kind':'source','source':{'id':'S2','title':'Private','url':'http://127.0.0.1/'}})
                tab.receive({'run_id':'old','kind':'source','source':{'id':'S3','title':'Late','url':'https://example.com/late'}})
                tab.job=None;tab.run_id=None
                saved=store.list_sessions()[0];self.assertEqual(len(saved['coding_sources']),1)
                self.assertEqual(saved['coding_sources'][0]['id'],'S1')
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);tab=window.tabs.currentWidget()
                self.assertEqual(tab.sources_button.text(),'Sources (1)')
                dialog=CodingSourcesDialog(tab,tab.session['coding_sources'])
                with patch('agentnik.code_ui.QDesktopServices.openUrl') as open_url:
                    open_url.assert_not_called();dialog.open_source();open_url.assert_called_once()
                    self.assertEqual(open_url.call_args.args[0].toString(),'https://example.com/docs')
                dialog.copy_source();self.assertEqual(app.clipboard().text(),'https://example.com/docs');dialog.close()
            finally:window.close();app.processEvents();store.db.close()

    def test_limits_dialog_persists_per_session_and_can_reset(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from agentnik.ui import Window
        from agentnik.code_ui import CodingLimitsDialog
        from agentnik.code_limits import coding_limits
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();values=coding_limits();values['rounds']=12;values['turn_seconds']=600;values['model_seconds']=480
                with patch('agentnik.code_ui.CodingLimitsDialog') as dialog:
                    dialog.return_value.exec.return_value=QDialog.DialogCode.Accepted;dialog.return_value.values.return_value=values;dialog.return_value.goal_values.return_value={'steps':4,'seconds':120}
                    tab.configure_limits()
                self.assertEqual(store.list_sessions()[0]['coding_limits'],values);self.assertEqual(store.list_sessions()[0]['coding_goal_limits'],{'steps':4,'seconds':120})
                dialog=CodingLimitsDialog(tab,values,{'steps':4,'seconds':120});self.assertEqual(dialog.fields['model_seconds'].value(),480);self.assertEqual(dialog.goal_fields['steps'].value(),4);dialog.reset();self.assertEqual(dialog.values(),coding_limits());self.assertEqual(dialog.goal_values(),{'steps':0,'seconds':0});dialog.close()
                window.close_tab(window.tabs.indexOf(tab));window.open_session(store.list_sessions()[0]);self.assertEqual(window.tabs.currentWidget().session['coding_limits'],values)
            finally:window.close();app.processEvents();store.db.close()

    def test_close_prompts_during_pending_coding_approval(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();window.stats();self.assertIn('Ready',window.statusBar().currentMessage())
                from agentnik.code_agent import CodingRun
                run=CodingRun({'model':'test'},str(project),'task');tab.job=run;tab.run_id=run.run_id
                tab.receive({'run_id':run.run_id,'kind':'edit_proposal','fingerprint':'one','proposal':{'cwd':str(project),'path':'file.py','diff':'+change'}})
                self.assertTrue(tab.approve.isEnabled());window.stats();self.assertIn('Running',window.statusBar().currentMessage())
                with patch('agentnik.ui.confirm',return_value=False) as confirm:
                    event=QCloseEvent();window.closeEvent(event);self.assertFalse(event.isAccepted());confirm.assert_called_once()
                self.assertIsNotNone(tab.job);self.assertTrue(tab.approve.isEnabled())
                with patch('agentnik.ui.confirm',return_value=True):
                    event=QCloseEvent();window.closeEvent(event);self.assertTrue(event.isAccepted())
                self.assertIsNone(tab.job);self.assertFalse(tab.approve.isEnabled())
                saved=next(s for s in store.list_sessions() if s['id']==session['id'])
                self.assertEqual(saved['code_state'],'cancelled')
            finally:window.close();app.processEvents();store.db.close()

    def test_missing_saved_connection_is_preserved_on_reopen(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident)
                session['coding_models']={'heavy':{'connection':'Missing','model':'saved-alias'}};store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();app.processEvents();tab.save_models()
                self.assertIn('unavailable',tab.roles['heavy'][0].currentText())
                self.assertEqual(tab.session['coding_models']['heavy'],{'connection':'Missing','model':'saved-alias'})
                with self.assertRaises(ValueError):tab.role_connection('heavy')
            finally:window.close();app.processEvents();store.db.close()

    def test_failed_run_can_be_saved_and_reopened(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['connections']={'Gateway':{'url':'https://gateway.example/v1','protocol':'chat','model':'heavy','stream':False}}
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Gateway'))
                tab.composer.setPlainText('Analyze')
                with patch.object(core,'open_request',side_effect=core.EndpointError(401,'private error')):
                    tab.start_coding();deadline=time.monotonic()+3
                    while tab.job is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    self.assertIsNone(tab.job)
                saved=next(s for s in store.list_sessions() if s['id']==session['id'])
                self.assertEqual(saved['code_state'],'failed');self.assertNotIn('private error',json.dumps(saved))
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents()
                self.assertEqual(window.tabs.currentWidget().composer.toPlainText(),'Analyze')
                self.assertIn('Coding stopped',window.tabs.currentWidget().activity.toPlainText())
            finally:window.close();app.processEvents();store.db.close()

    def test_limited_run_reopens_and_repeated_continuation_keeps_task_and_draft(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        app=QApplication.instance() or QApplication([]);runs=[]
        def run(job,emit):
            runs.append(job)
            emit({'run_id':job.run_id,'kind':'output','text':'Evidence '+str(len(runs))})
            emit({'run_id':job.run_id,'kind':'finished','status':'failed' if len(runs)<3 else 'completed','limited':len(runs)<3,'text':'Limit reached' if len(runs)<3 else 'Done'})
        def settle(tab):
            deadline=time.monotonic()+4
            while tab.job is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertIsNone(tab.job)
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(CodingRun,'run',run):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');store.config['connections']={'Gateway':{'url':'https://gateway.example/v1','protocol':'chat','model':'heavy','stream':False}}
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Gateway'));tab.composer.setPlainText('Original coding task');image_path=store.attach(data=b'fixture image',suffix='.png');tab.attachments.set_paths([image_path]);tab.start_coding();settle(tab)
                saved=next(s for s in store.list_sessions() if s['id']==session['id']);self.assertEqual(saved['code_state'],'limited');self.assertEqual(saved['coding_resume']['task'],'Original coding task')
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents();tab=window.tabs.currentWidget();self.assertTrue(tab.continue_button.isEnabled())
                tab.composer.setPlainText('Unsent coding draft');tab.attachments.set_paths([]);tab.continue_button.click();settle(tab)
                self.assertEqual(tab.composer.toPlainText(),'Unsent coding draft');self.assertEqual(runs[-1].resume_context['task'],'Original coding task')
                self.assertEqual(runs[-1].images,[image_path])
                tab.continue_button.click();settle(tab)
                self.assertEqual(runs[-1].resume_context['task'],'Original coding task');self.assertIn('Evidence 1',runs[-1].resume_context['evidence']);self.assertIn('Evidence 2',runs[-1].resume_context['evidence'])
                self.assertEqual(tab.composer.toPlainText(),'Unsent coding draft');self.assertFalse(tab.continue_button.isEnabled())
            finally:window.close();app.processEvents();store.db.close()

    def test_continue_starts_new_budget_after_actual_round_limit(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.code_limits import coding_limits
        app=QApplication.instance() or QApplication([]);bodies=[]
        replies=[Wire(chat(calls=[call('list_files',{'path':'.'})],finish='tool_calls'),False),Wire(chat(calls=[call('list_files',{'path':'.'})],finish='tool_calls'),False),Wire(chat('Continued successfully'),False)]
        def send(connection,url,body,timeout):
            bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        def settle(tab):
            deadline=time.monotonic()+4
            while tab.job is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertIsNone(tab.job)
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'open_request',side_effect=send):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');store.config['connections']={'Gateway':{'url':'https://gateway.example/v1','protocol':'chat','model':'heavy','stream':False}}
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);limits=coding_limits();limits['rounds']=1;session['coding_limits']=limits;store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Gateway'));tab.composer.setPlainText('Inspect this project');tab.start_coding();settle(tab)
                self.assertEqual(len(bodies),2);self.assertTrue(tab.continue_button.isEnabled());tab.continue_button.click();settle(tab)
                self.assertEqual(len(bodies),3);self.assertIn('Inspect this project',json.dumps(bodies[-1]));self.assertEqual(tab.session['code_state'],'completed')
                self.assertNotIn('tool_calls',json.dumps(bodies[-1]['messages']))
            finally:window.close();app.processEvents();store.db.close()

    def test_selected_connection_edits_only_after_approval_and_restores_roles(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        def settle(predicate):
            deadline=time.monotonic()+3
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['connections']={'Gateway':{'url':'https://gateway.example/v1','protocol':'chat','model':'heavy-default','api_key':'private-model-key','stream':False}}
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();app.processEvents()
                for role,model in [('heavy','my-heavy-coder')]:
                    combo,field=tab.roles[role];combo.setCurrentIndex(combo.findData('Gateway'));field.setText(model)
                tab.composer.setPlainText('Create a test file')
                replies=[Wire(chat(calls=[call('write_file',{'path':'test.txt','content':'approved content'})],finish='tool_calls'),False),Wire(chat('Created test.txt'),False)]
                with patch.object(core,'open_request',side_effect=replies) as endpoint,patch('subprocess.Popen') as process:
                    tab.start_coding();settle(lambda:tab.job is None)
                    self.assertTrue(tab.approval_panel.isHidden());self.assertIn('Applied project edit',tab.activity.toPlainText())
                    self.assertEqual((project/'test.txt').read_text(),'approved content');self.assertEqual(endpoint.call_count,2);process.assert_not_called()
                saved=next(s for s in store.list_sessions() if s['id']==session['id'])
                self.assertNotIn('private-model-key',json.dumps(saved))
                self.assertEqual(saved['coding_context']['task'],'Create a test file')
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents()
                reopened=window.tabs.currentWidget();self.assertEqual(reopened.roles['heavy'][1].text(),'my-heavy-coder')
                self.assertEqual(set(reopened.roles),{'heavy','decision'});self.assertIsNone(reopened.job)
                self.assertIn('Created test.txt',reopened.session['coding_context']['answer']);self.assertFalse(reopened.use_context.isChecked())
                reopened.use_context.setChecked(True);reopened.composer.setPlainText('Follow up');bodies=[]
                def reply(c,url,body,timeout):bodies.append(body);return Wire(chat('Follow-up complete'),False)
                with patch.object(core,'open_request',side_effect=reply):
                    reopened.start_coding();settle(lambda:reopened.job is None)
                self.assertIn('Create a test file',json.dumps(bodies[0]));self.assertIn('Created test.txt',json.dumps(bodies[0]))
                self.assertFalse(reopened.use_context.isChecked())
            finally:window.close();app.processEvents();store.db.close()

if __name__=='__main__':unittest.main()

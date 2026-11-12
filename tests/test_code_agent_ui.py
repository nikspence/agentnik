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
from test_code_agent import call

class CodingWorkspace(unittest.TestCase):
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
                tab.light_enabled.setChecked(False);tab.composer.setPlainText('task')
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
                for operation,label in [('git_stage','STAGE FILES'),('git_unstage','UNSTAGE FILES'),('git_create_branch','CREATE BRANCH'),('git_commit_staged','GIT COMMIT')]:
                    proposal={'operation':operation,'cwd':str(project),'path':'one.txt','paths':['one.txt'],'diff':'-old\n+new\n','head':'a'*40,'name':'feature/review','identity':'Test <test@example.invalid>','message':'Reviewed snapshot'}
                    tab.receive({'run_id':'git-run','kind':'operation_proposal','fingerprint':operation,'proposal':proposal})
                    self.assertFalse(tab.approval_panel.isHidden());self.assertIn(label,tab.approval.toPlainText())
                    self.assertEqual(tab.diff.isHidden(),operation=='git_create_branch');self.assertTrue(tab.advice_label.isHidden())
                    tab.decide(False);self.assertTrue(tab.approval_panel.isHidden())
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
                        tab.start_coding();self.assertEqual(run.call_args.kwargs['search_provider'],'managed');self.assertEqual(run.call_args.args[5],[])
                    with patch.object(store,'web_backend_specs',return_value=[{'id':'brave','kind':'brave','key':'brave-test-key'},{'id':'ollama','kind':'ollama','key':'ollama-test-key'}]):
                        tab.start_coding();self.assertEqual(run.call_args.kwargs['search_provider'],'managed');self.assertEqual([b['kind'] for b in run.call_args.args[5]],['brave'])
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
                    dialog.return_value.exec.return_value=QDialog.DialogCode.Accepted;dialog.return_value.values.return_value=values
                    tab.configure_limits()
                self.assertEqual(store.list_sessions()[0]['coding_limits'],values)
                dialog=CodingLimitsDialog(tab,values);self.assertEqual(dialog.fields['model_seconds'].value(),480);dialog.reset();self.assertEqual(dialog.values(),coding_limits());dialog.close()
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
                tab.start_simulation();deadline=time.monotonic()+3
                while not tab.approve.isEnabled() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
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
                for role,model in [('heavy','my-heavy-coder'),('light','my-light-coder')]:
                    combo,field=tab.roles[role];combo.setCurrentIndex(combo.findData('Gateway'));field.setText(model)
                tab.light_enabled.setChecked(False)
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
                self.assertEqual(reopened.roles['light'][1].text(),'my-light-coder');self.assertFalse(reopened.light_enabled.isChecked());self.assertIsNone(reopened.job)
                self.assertIn('Created test.txt',reopened.context_view.toPlainText());self.assertFalse(reopened.use_context.isChecked())
                reopened.use_context.setChecked(True);reopened.composer.setPlainText('Follow up');bodies=[]
                def reply(c,url,body,timeout):bodies.append(body);return Wire(chat('Follow-up complete'),False)
                with patch.object(core,'open_request',side_effect=reply):
                    reopened.start_coding();settle(lambda:reopened.job is None)
                self.assertIn('Create a test file',json.dumps(bodies[0]));self.assertIn('Created test.txt',json.dumps(bodies[0]))
                self.assertFalse(reopened.use_context.isChecked())
            finally:window.close();app.processEvents();store.db.close()

if __name__=='__main__':unittest.main()

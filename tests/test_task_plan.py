"""Task plans: metadata-only model tools and persistent offscreen checklists."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from agentnik import core
from agentnik.task_plan import validate_plan,parse_update
from agentnik.code_agent import CodingRun
from agentnik.sessions import validate_session,SessionError
from agentnik.storage import Store
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

PLAN={'explanation':'Inspect, change, then check.','steps':[{'step':'Inspect the project','status':'completed'},{'step':'Implement the change','status':'in_progress'},{'step':'Check the result','status':'pending'}]}


class PlanContracts(unittest.TestCase):
    def test_valid_plan_is_copied_and_bad_shapes_are_rejected(self):
        self.assertEqual(parse_update(PLAN['explanation'],json.dumps(PLAN['steps'])),PLAN)
        result=validate_plan(PLAN);result['steps'][0]['step']='different';self.assertNotEqual(result,PLAN)
        bad=[{}, {'explanation':'','steps':[]},{'explanation':'x'*1001,'steps':PLAN['steps']},{'explanation':'','steps':[{'step':'x','status':'invented'}]},{'explanation':'','steps':[{'step':'x','status':'in_progress'}]*2},{'explanation':'','steps':[{'step':'x','status':'pending'}]*21},{'explanation':'','steps':[{'step':'line\nbreak','status':'pending'}]},{'explanation':'','steps':[{'step':'x','status':'pending','command':'do not run'}]}]
        for value in bad:
            with self.subTest(value=str(value)[:80]),self.assertRaises(ValueError):validate_plan(value)
        with self.assertRaises(ValueError):parse_update('','not json')

    def test_model_can_create_read_and_update_plan_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            final=copy.deepcopy(PLAN);final['steps'][1]['status']='blocked'
            replies=[Wire(chat(calls=[call('update_plan',{'explanation':PLAN['explanation'],'steps':json.dumps(PLAN['steps'])}),call('get_plan',{},'read'),call('update_plan',{'explanation':final['explanation'],'steps':json.dumps(final['steps'])},'update')],finish='tool_calls'),False),Wire(chat('Work is blocked'),False)];events=[];bodies=[]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            run=CodingRun(dict(C,stream=False),folder,'Plan the work')
            with patch.object(core,'open_request',side_effect=send),patch('subprocess.Popen',side_effect=AssertionError('Plans must not execute')):
                run.run(events.append)
            self.assertEqual([e['plan'] for e in events if e['kind']=='plan'],[PLAN,final]);self.assertEqual(run.plan,final)
            results=[json.loads(m['content']) for m in bodies[1]['messages'] if m['role']=='tool']
            self.assertEqual(results[1]['plan'],PLAN);self.assertFalse(any(e['kind'] in ('edit_proposal','operation_proposal') for e in events));self.assertEqual(events[-1]['status'],'completed')
            self.assertEqual(final['steps'][1]['status'],'blocked')

    def test_invalid_or_secret_plan_does_not_emit_plan_updates(self):
        for steps in ('[]',json.dumps([{'step':'contains model-secret','status':'pending'}])):
            with tempfile.TemporaryDirectory() as folder:
                events=[];replies=[Wire(chat(calls=[call('update_plan',{'explanation':'','steps':steps})],finish='tool_calls'),False),Wire(chat('Stopped'),False)]
                run=CodingRun(dict(C,stream=False,api_key='model-secret'),folder,'Plan')
                with patch.object(core,'open_request',side_effect=replies):run.run(events.append)
                self.assertIsNone(run.plan);self.assertFalse(any(e['kind']=='plan' for e in events));self.assertNotIn('model-secret',json.dumps(events))

    def test_session_validation_preserves_legacy_sessions_and_rejects_bad_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'data')
            try:
                from agentnik.repositories import RepositoryRegistry
                registry=RepositoryRegistry(store);project=Path(folder)/'project';project.mkdir();session=registry.session(registry.put(project))
                self.assertNotIn('coding_plan',validate_session(session))
                session['coding_plan']=PLAN;self.assertEqual(validate_session(session)['coding_plan'],PLAN)
                session['coding_plan']={'steps':[]}
                with self.assertRaises(SessionError):validate_session(session)
            finally:store.db.close()


class PlanWorkspace(unittest.TestCase):
    def test_plan_is_collapsible_read_only_persistent_and_ignores_late_events(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(folder);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                self.assertTrue(tab.plan_toggle.isHidden());tab.job=MagicMock();tab.run_id='active'
                tab.receive({'run_id':'old','kind':'plan','plan':PLAN});self.assertNotIn('coding_plan',tab.session)
                tab.receive({'run_id':'active','kind':'plan','plan':PLAN})
                self.assertFalse(tab.plan_toggle.isHidden());self.assertTrue(tab.plan_panel.isHidden());self.assertEqual(tab.plan_list.count(),3)
                self.assertFalse(tab.plan_list.item(0).flags() & Qt.ItemFlag.ItemIsUserCheckable);self.assertEqual(tab.plan_list.item(0).checkState(),Qt.CheckState.Checked)
                tab.plan_toggle.click();self.assertFalse(tab.plan_panel.isHidden());tab.cancel();self.assertEqual(store.list_sessions()[0]['coding_plan'],PLAN)
                tab.receive({'run_id':'active','kind':'plan','plan':{'explanation':'late','steps':[{'step':'Late','status':'completed'}]}});self.assertEqual(tab.session['coding_plan'],PLAN)
                window.close_tab(window.tabs.indexOf(tab))
                with patch.object(core,'open_request') as request,patch('subprocess.Popen') as execute:
                    window.open_session(store.list_sessions()[0]);reopened=window.tabs.currentWidget();request.assert_not_called();execute.assert_not_called()
                self.assertEqual(reopened.session['coding_plan'],PLAN);self.assertTrue(reopened.plan_panel.isHidden());self.assertIsNone(reopened.job)
            finally:window.close();app.processEvents();store.db.close()

    def test_new_coding_run_clears_previous_task_plan(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(folder);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['coding_plan']=PLAN;store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                run=CodingRun(dict(C,stream=False),str(project),'New task')
                with patch.object(run,'run') as execute:
                    tab.launch(run,'New coding task');tab.worker.join(1);self.assertNotIn('coding_plan',tab.session);self.assertTrue(tab.plan_toggle.isHidden());execute.assert_called_once()
                tab.cancel()
            finally:window.close();app.processEvents();store.db.close()

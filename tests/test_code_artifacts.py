import json
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_artifacts import Artifacts,validate_notes
from agentnik.code_agent import CodingRun
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire


class CodingArtifacts(unittest.TestCase):
    def test_artifact_bounds_search_and_read(self):
        store=Artifacts();item=store.add('before needle after','tests')
        self.assertEqual(store.search(item['id'],'needle')['matches'][0]['offset'],7)
        self.assertEqual(store.read(item['id'],'7','6')['text'],'needle')
        with self.assertRaises(ValueError):store.read(item['id'],'0','8001')
        with self.assertRaises(ValueError):validate_notes({'x':'a'*4001})

    def test_mcp_artifacts_use_bounded_per_item_and_total_storage(self):
        with patch('agentnik.code_artifacts.MAX_ARTIFACT_CHARS',5),patch('agentnik.code_artifacts.MAX_MCP_ARTIFACT_CHARS',12),patch('agentnik.code_artifacts.MAX_ARTIFACT_TOTAL_CHARS',15):
            store=Artifacts();item=store.add('abcdefghij','mcp_result');self.assertEqual(store.read(item['id'],'3','4')['text'],'defg')
            with self.assertRaises(ValueError):store.add('x'*6,'run_tests')
            with self.assertRaises(ValueError):store.add('x'*13,'mcp_result')
            store.add('x'*5,'run_tests')
            with self.assertRaises(ValueError):store.add('x','mcp_result')

    def test_model_can_search_oversized_mcp_result_without_repeating_call(self):
        from unittest.mock import Mock
        from agentnik.code_limits import coding_limits
        marker='account-target-near-end';output='Evidence '*30000+marker+' model-secret-value'
        detail={'name':'query','description':'Query','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as root:
            bridge=Mock();bridge.server={'name':'Database','command':'server','args':[],'enabled':True};bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'text','text':output},{'type':'text','text':'private-user-only','annotations':{'audience':['user']}}]}}]
            limits=coding_limits();limits['context_bytes']=12000;events=[];bodies=[];run=CodingRun(dict(C,stream=False,api_key='model-secret-value'),root,'Inspect',limits=limits,mcp_bridge=bridge)
            def request(c,url,body,timeout):
                bodies.append(json.loads(json.dumps(body)));turn=len(bodies)
                if turn==1:return Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False)
                if turn==2:return Wire(chat(calls=[call('mcp_call',{'tool':'query','arguments':'{}'})],finish='tool_calls'),False)
                if turn==3:
                    payload=json.loads(bodies[-1]['messages'][-1]['content']);self.assertEqual(payload['data']['artifact']['id'],'A1');self.assertIn('search_artifact',payload['data']['artifact_notice'])
                    return Wire(chat(calls=[call('search_artifact',{'id':'A1','query':marker})],finish='tool_calls'),False)
                if turn==4:
                    found=json.loads(bodies[-1]['messages'][-1]['content']);offset=found['matches'][0]['offset']
                    return Wire(chat(calls=[call('read_artifact',{'id':'A1','offset':str(offset),'length':'100'})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch('agentnik.core.open_request',side_effect=request):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual([item.args[0] for item in bridge.request.call_args_list],['discover','call'])
            payload=json.loads(bodies[-1]['messages'][-1]['content']);self.assertIn(marker,payload['text']);self.assertNotIn('model-secret-value',json.dumps(bodies));self.assertNotIn('model-secret-value',run.artifacts.items['A1']['text']);self.assertNotIn('private-user-only',run.artifacts.items['A1']['text'])

    def test_oversized_result_reports_when_artifact_storage_is_unavailable(self):
        from unittest.mock import Mock
        from agentnik.code_limits import coding_limits
        detail={'name':'query','description':'Query','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as root:
            bridge=Mock();bridge.server={'name':'Database','command':'server','args':[],'enabled':True};bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'text','text':'x'*30000}]}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'query','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[];limits=coding_limits();limits['context_bytes']=12000
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.core.open_request',side_effect=request),patch('agentnik.code_artifacts.MAX_MCP_ARTIFACT_CHARS',100):CodingRun(dict(C,stream=False),root,'Inspect',limits=limits,mcp_bridge=bridge).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);payload=json.loads(bodies[-1]['messages'][-1]['content']);self.assertTrue(payload['data']['artifact_unavailable']);self.assertIn('could not be retained',payload['data']['artifact_notice'])
            self.assertEqual([item.args[0] for item in bridge.request.call_args_list],['discover','call'])

    def test_model_can_retrieve_artifact_note_and_test_report(self):
        with tempfile.TemporaryDirectory() as root:
            calls1=[call('write_note',{'name':'decision','text':'Keep API stable'},'n'),call('run_tests',{'path':'.','command':'tests','format':'auto'},'t')]
            calls2=[call('read_note',{'name':'decision'},'r'),call('read_artifact',{'id':'A1','offset':'1990','length':'30'},'a'),call('get_test_report',{'failure':''},'s')]
            replies=[Wire(chat(calls=calls1,finish='tool_calls'),False),Wire(chat(calls=calls2,finish='tool_calls'),False),Wire(chat('Done'),False)]
            bodies=[];events=[];run=CodingRun(dict(C,stream=False),root,'Run tests')
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            output='x'*2000+'needle\nRan 1 test in 0.1s\nOK\n'
            with patch('agentnik.core.open_request',side_effect=request),patch('agentnik.shell.execute',return_value={'exit_code':0,'output':output,'truncated':False}):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed')
            self.assertEqual(next(e for e in events if e['kind']=='working_notes')['notes'],{'decision':'Keep API stable'})
            payload=[json.loads(m['content']) for m in bodies[-1]['messages'] if m.get('role')=='tool']
            self.assertTrue(any(p.get('output_artifact',{}).get('id')=='A1' for p in payload))
            self.assertTrue(any('needle' in p.get('text','') for p in payload))
            self.assertTrue(any(p.get('report',{}).get('outcome')=='passed' for p in payload))

    def test_notes_persist_and_can_be_edited_in_dialog(self):
        import os
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QDialog,QDialogButtonBox,QPlainTextEdit
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);folder=root/'project';folder.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(folder);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();run=CodingRun(dict(C,stream=False),str(folder),'task');tab.job=run;tab.run_id=run.run_id
                tab.receive({'run_id':run.run_id,'kind':'working_notes','notes':{'finding':'original'}})
                tab.job=None;tab.run_id=None
                self.assertEqual(store.list_sessions()[0]['coding_working_notes'],{'finding':'original'})
                def edit():
                    dialog=app.activeModalWidget();dialog.findChild(QPlainTextEdit).setPlainText('{"finding":"edited"}')
                    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
                QTimer.singleShot(0,edit);tab.edit_working_notes()
                self.assertEqual(store.list_sessions()[0]['coding_working_notes'],{'finding':'edited'})
            finally:window.close();app.processEvents();store.db.close()

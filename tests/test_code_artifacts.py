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

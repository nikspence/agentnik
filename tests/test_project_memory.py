"""Project memory isolation, review, and optimistic concurrency."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik.storage import Store
from agentnik.repositories import RepositoryRegistry
from agentnik.project_memory import ProjectMemory,digest
from agentnik.code_agent import CodingRun
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

ENTRY={'title':'Tests','text':'Run unittest','source':'README.md','stale':False}

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name);(root/'one').mkdir();(root/'two').mkdir()
        self.store=Store(root/'data');registry=RepositoryRegistry(self.store);self.one=registry.put(root/'one');self.two=registry.put(root/'two');self.root=root
        self.memory=ProjectMemory(self.store.root/'history.sqlite3',self.one)
    def tearDown(self):self.store.db.close();self.temp.cleanup()

    def test_isolation_search_stale_write_and_delete(self):
        item=self.memory.save(ENTRY);self.assertEqual(self.memory.search('unittest')[0]['id'],item['id']);self.assertEqual(item['created'],item['updated'])
        other=ProjectMemory(self.store.root/'history.sqlite3',self.two);self.assertEqual(other.list(),[])
        self.memory.save({**ENTRY,'text':'Changed'},item['id'],digest(ENTRY))
        with self.assertRaises(ValueError):self.memory.save(ENTRY,item['id'],digest(ENTRY))
        with self.assertRaises(ValueError):self.memory.delete(item['id'],digest(ENTRY))
        self.assertEqual(self.memory.read(item['id'])['text'],'Changed')
        self.memory.delete(item['id']);self.assertEqual(self.memory.list(),[])

    def test_model_proposal_requires_approval_and_reads_only_on_request(self):
        for allow in (False,True):
            with self.subTest(allow=allow):
                args={'id':'','title':'Design','text':'Keep API stable','source':'docs/api.md','stale':'false'}
                replies=[Wire(chat(calls=[call('propose_memory',args)],finish='tool_calls'),False),Wire(chat('Done'),False)]
                bodies=[];events=[];run=CodingRun(dict(C,stream=False),str(self.root/'one'),'work',project_memory=self.memory)
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':
                        self.assertEqual(event['proposal']['entry']['source'],'docs/api.md');run.decide(event['fingerprint'],allow)
                with patch('agentnik.core.open_request',side_effect=send):run.run(emit)
                self.assertEqual(events[-1]['status'],'completed');self.assertEqual(len(self.memory.list()),int(allow))
                self.assertNotIn('Keep API stable',json.dumps(bodies[0]))

    def test_search_and_read_from_later_coding_run(self):
        item=self.memory.save(ENTRY)
        replies=[Wire(chat(calls=[call('search_memory',{'query':'unittest'},'search')],finish='tool_calls'),False),Wire(chat(calls=[call('read_memory',{'id':item['id']},'read')],finish='tool_calls'),False),Wire(chat('Done'),False)]
        bodies=[];run=CodingRun(dict(C,stream=False),str(self.root/'one'),'follow up',project_memory=ProjectMemory(self.store.root/'history.sqlite3',self.one))
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch('agentnik.core.open_request',side_effect=send):run.run(lambda event:None)
        self.assertNotIn('Run unittest',json.dumps(bodies[0]))
        self.assertIn(item['id'],json.dumps(bodies[1]));self.assertIn('Run unittest',json.dumps(bodies[2]))

    def test_concurrent_update_invalidates_approved_proposal(self):
        item=self.memory.save(ENTRY)
        args={'id':item['id'],'title':'Tests','text':'New','source':'README.md','stale':'false'}
        replies=[Wire(chat(calls=[call('propose_memory',args)],finish='tool_calls'),False),Wire(chat('Done'),False)]
        bodies=[];run=CodingRun(dict(C,stream=False),str(self.root/'one'),'work',project_memory=self.memory)
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        def emit(event):
            if event['kind']=='operation_proposal':
                self.memory.save({**ENTRY,'text':'Concurrent'},item['id']);run.decide(event['fingerprint'],True)
        with patch('agentnik.core.open_request',side_effect=send):run.run(emit)
        self.assertEqual(self.memory.read(item['id'])['text'],'Concurrent')
        self.assertIn('changed since review',json.dumps(bodies[-1]))

    def test_manager_edits_and_approval_renders_full_proposal(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QDialogButtonBox,QPlainTextEdit,QPushButton
        from agentnik import core
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            window=Window(self.store)
            try:
                session=window.repositories.session(self.one);self.store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def create():
                    dialog=app.activeModalWidget();dialog.findChild(QPlainTextEdit).setPlainText(json.dumps(ENTRY))
                    next(b for b in dialog.findChildren(QPushButton) if b.text()=='Save').click()
                    dialog.reject()
                QTimer.singleShot(0,create);tab.edit_project_memory()
                self.assertEqual(self.memory.list()[0]['text'],'Run unittest')
                run=CodingRun(dict(C,stream=False),str(self.root/'one'),'work');tab.job=run;tab.run_id=run.run_id
                tab.receive({'run_id':run.run_id,'kind':'operation_proposal','fingerprint':'f','proposal':{'operation':'project_memory','cwd':str(self.root/'one'),'id':'','entry':ENTRY,'previous':None}})
                self.assertIn('Run unittest',tab.approval.toPlainText());self.assertIn('README.md',tab.approval.toPlainText());self.assertTrue(tab.approve.isEnabled())
                tab.cancel()
            finally:window.close();app.processEvents()

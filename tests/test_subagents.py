"""Bounded parallel delegation and skill update checks with mocked endpoints."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from agentnik import core
from agentnik.code_agent import CodingRun
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

class Subagents(unittest.TestCase):
    def test_parallel_children_share_light_connection_and_cannot_call_tools(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'.agents/skills/review';folder.mkdir(parents=True)
            (folder/'SKILL.md').write_text('---\nname: review\ndescription: Review\n---\nRespect project style.',encoding='utf-8')
            barrier=threading.Barrier(2);bodies=[];lock=threading.Lock();events=[];heavy_count=0
            heavy=dict(C,stream=False);light=dict(C,model='light',stream=False)
            def send(c,url,body,timeout):
                nonlocal heavy_count
                with lock:bodies.append(copy.deepcopy(body))
                if c['model']=='light':
                    barrier.wait(timeout=5)
                    return Wire(chat('Finding'),False)
                heavy_count+=1
                if heavy_count==1:return Wire(chat(calls=[call('delegate_parallel',{'tasks':json.dumps(['Review interfaces','Check documentation'])})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(heavy,root,'Review',light=light,skills=['review']).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events)
            children=[body for body in bodies if body['model']=='light'];self.assertEqual(len(children),2)
            self.assertTrue(all('tools' not in body for body in children));self.assertTrue(all('Respect project style.' in json.dumps(body) for body in children))
            results=[json.loads(message['content']) for message in bodies[-1]['messages'] if message['role']=='tool']
            self.assertEqual([item['status'] for item in results[-1]['subagents']],['completed','completed'])
            self.assertEqual(sum(' started · ' in event.get('text','') for event in events),2)

    def test_modified_selected_skill_invalidates_pending_approval(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'.agents/skills/review';folder.mkdir(parents=True)
            skill=folder/'SKILL.md';skill.write_text('---\nname: review\ndescription: Review\n---\nOriginal',encoding='utf-8')
            run=CodingRun(dict(C,stream=False),root,'Create folder',skills=['review']);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':
                    skill.write_text('---\nname: review\ndescription: Review\n---\nChanged',encoding='utf-8');run.decide(event['fingerprint'],True)
            replies=[Wire(chat(calls=[call('create_directory',{'path':'new'})],finish='tool_calls'),False)]
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertFalse((Path(root)/'new').exists());self.assertEqual(events[-1]['status'],'failed');self.assertIn('skill changed',events[-1]['text'].lower())

    def test_partial_failure_is_attributed_without_replay(self):
        with tempfile.TemporaryDirectory() as root:
            bodies=[];lock=threading.Lock();events=[];heavy_count=0
            def send(c,url,body,timeout):
                nonlocal heavy_count
                with lock:bodies.append(copy.deepcopy(body))
                if c['model']=='light':
                    if 'bad task' in json.dumps(body):return Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo fail'})],finish='tool_calls'),False)
                    return Wire(chat('Useful finding'),False)
                heavy_count+=1
                if heavy_count==1:return Wire(chat(calls=[call('delegate_parallel',{'tasks':json.dumps(['bad task','good task'])})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Review',light=dict(C,model='light',stream=False)).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(sum(b['model']=='light' for b in bodies),2)
            tool=next(json.loads(m['content']) for m in bodies[-1]['messages'] if m['role']=='tool')
            self.assertEqual([x['status'] for x in tool['subagents']],['failed','completed']);self.assertIn('unavailable tools',tool['subagents'][0]['error'])

    def test_request_budget_prevents_starting_partial_batch(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as root:
            limits=coding_limits();limits['requests']=2;events=[];calls=[]
            def send(c,url,body,timeout):
                calls.append(c['model']);return Wire(chat(calls=[call('delegate_parallel',{'tasks':json.dumps(['first','second'])})],finish='tool_calls'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Review',light=dict(C,model='light',stream=False),limits=limits).run(events.append)
            self.assertEqual(calls,['heavy']);self.assertEqual(events[-1]['status'],'failed');self.assertIn('limit',events[-1]['text'].lower())

    def test_cancellation_stops_parallel_run_without_late_result(self):
        import time
        with tempfile.TemporaryDirectory() as root:
            started=threading.Event();release=threading.Event();events=[];counter=[0];lock=threading.Lock()
            def send(c,url,body,timeout):
                if c['model']=='light':
                    with lock:
                        counter[0]+=1
                        if counter[0]==2:started.set()
                    release.wait(5);return Wire(chat('Late result'),False)
                return Wire(chat(calls=[call('delegate_parallel',{'tasks':json.dumps(['one','two'])})],finish='tool_calls'),False)
            run=CodingRun(dict(C,stream=False),root,'Review',light=dict(C,model='light',stream=False))
            with patch.object(core,'open_request',side_effect=send):
                thread=threading.Thread(target=run.run,args=(events.append,));thread.start()
                try:
                    self.assertTrue(started.wait(5),events);run.stop();thread.join(5);self.assertFalse(thread.is_alive())
                finally:release.set();thread.join(5)
            self.assertFalse(any('Late result' in e.get('text','') for e in events))

    def test_skill_update_during_model_request_stops_before_completion(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'.agents/skills/review';folder.mkdir(parents=True)
            skill=folder/'SKILL.md';skill.write_text('---\nname: review\ndescription: Review\n---\nOriginal',encoding='utf-8')
            events=[]
            def send(c,url,body,timeout):
                skill.write_text('---\nname: review\ndescription: Review\n---\nChanged',encoding='utf-8')
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Review',skills=['review']).run(events.append)
            self.assertEqual(events[-1]['status'],'failed');self.assertIn('skill changed',events[-1]['text'].lower())

    def test_file_snapshots_require_individual_approval_and_redact_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'a.txt').write_text('data model-secret',encoding='utf-8')
            (Path(root)/'b.txt').write_text('other data',encoding='utf-8')
            bodies=[];events=[];heavy_count=0;run=CodingRun(dict(C,stream=False,api_key='model-secret'),root,'Review',light=dict(C,model='light',stream=False))
            def send(c,url,body,timeout):
                nonlocal heavy_count
                bodies.append(copy.deepcopy(body))
                if c['model']=='light':return Wire(chat('Finding'),False)
                heavy_count+=1
                if heavy_count==1:return Wire(chat(calls=[call('delegate_parallel',{'tasks':json.dumps([{'task':'Inspect a','paths':['a.txt']},{'task':'Inspect b','paths':['b.txt']}])})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':
                    self.assertEqual(event['proposal']['operation'],'subagent_file_transfer')
                    self.assertEqual(event['proposal']['destination'],'https://gateway.example/v1/chat/completions')
                    self.assertTrue(run.decide(event['fingerprint'],True))
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events)
            proposals=[e['proposal'] for e in events if e['kind']=='operation_proposal']
            self.assertEqual([p['path'] for p in proposals],['a.txt','b.txt']);self.assertEqual(proposals[0]['diff'],'data [redacted]')
            children=[b for b in bodies if b['model']=='light'];self.assertEqual(len(children),2)
            self.assertIn('data [redacted]',json.dumps(children));self.assertNotIn('model-secret',json.dumps(children)+json.dumps(events))
            self.assertTrue(all('tools' not in b for b in children))

    def test_rejected_or_changed_file_never_reaches_light(self):
        for reject in (True,False):
            with self.subTest(reject=reject),tempfile.TemporaryDirectory() as root:
                file=Path(root)/'a.txt';file.write_text('original',encoding='utf-8');events=[];calls=[];heavy_count=0
                run=CodingRun(dict(C,stream=False),root,'Review',light=dict(C,model='light',stream=False))
                def send(c,url,body,timeout):
                    nonlocal heavy_count
                    calls.append(c['model']);heavy_count+=1
                    if heavy_count==1:return Wire(chat(calls=[call('delegate_parallel',{'tasks':json.dumps([{'task':'Inspect','paths':['a.txt']},'Other'])})],finish='tool_calls'),False)
                    return Wire(chat('Stopped'),False)
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':
                        if not reject:file.write_text('changed',encoding='utf-8')
                        run.decide(event['fingerprint'],not reject)
                with patch.object(core,'open_request',side_effect=send):run.run(emit)
                self.assertNotIn('light',calls);self.assertEqual(events[-1]['status'],'completed')

    def test_nested_guidance_defers_file_transfer_until_model_sees_it(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'src';folder.mkdir();(folder/'AGENTS.md').write_text('Use local conventions.',encoding='utf-8');(folder/'a.txt').write_text('data',encoding='utf-8')
            events=[];bodies=[];heavy_count=0;run=CodingRun(dict(C,stream=False),root,'Review',light=dict(C,model='light',stream=False))
            tasks=json.dumps([{'task':'Inspect','paths':['src/a.txt']},'Other'])
            def send(c,url,body,timeout):
                nonlocal heavy_count
                bodies.append(copy.deepcopy(body))
                if c['model']=='light':return Wire(chat('Finding'),False)
                heavy_count+=1
                if heavy_count<=2:return Wire(chat(calls=[call('delegate_parallel',{'tasks':tasks})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(sum(e['kind']=='operation_proposal' for e in events),1)
            heavy=[b for b in bodies if b['model']=='heavy'];self.assertIn('Use local conventions.',heavy[1]['messages'][0]['content'])

    def test_code_pane_displays_file_and_destination_before_approval(self):
        import os
        from unittest.mock import MagicMock
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.storage import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.job=MagicMock();tab.run_id='active'
                proposal={'operation':'subagent_file_transfer','cwd':str(project),'path':'sample.txt','model':'light','destination':'https://example.org/v1/chat/completions','child':1,'task':'Review file','diff':'Exact approved text','source_sha256':'a'*64,'payload_sha256':'b'*64,'payload_bytes':19}
                tab.receive({'kind':'operation_proposal','run_id':'active','fingerprint':'f','proposal':proposal})
                self.assertFalse(tab.approval_panel.isHidden());self.assertFalse(tab.diff.isHidden())
                self.assertIn('sample.txt',tab.approval.toPlainText());self.assertIn('https://example.org',tab.approval.toPlainText());self.assertIn('light',tab.approval.toPlainText());self.assertEqual(tab.diff.toPlainText(),'Exact approved text')
            finally:
                if window.tabs.currentWidget():window.tabs.currentWidget().job=None
                window.close();app.processEvents();store.db.close()

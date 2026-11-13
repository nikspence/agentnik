"""User-configured independent review with mocked endpoints and offscreen Qt."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from agentnik import core
from agentnik.direct_review import DirectReviewRun
from test_compat_tools import chat, msg
from test_routing import Wire, message, response

MODEL={'url':'https://example.invalid/v1','protocol':'chat','model':'reviewer','stream':False}


class DirectReview(unittest.TestCase):
    def test_streamed_protocol_results_reach_the_findings_view(self):
        output='{"version":1,"findings":[]}'
        cases=[('chat',dict(MODEL,stream=True),[{'choices':[{'delta':{'content':output},'finish_reason':'stop'}]}]),
               ('messages',dict(MODEL,protocol='messages',stream=True),[
                   {'type':'message_start','message':{'role':'assistant','content':[]}},
                   {'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},
                   {'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':output}},
                   {'type':'content_block_stop','index':0},
                   {'type':'message_delta','delta':{'stop_reason':'end_turn'}},
                   {'type':'message_stop'}]),
               ('responses',dict(MODEL,protocol='responses',stream=True),[{'type':'response.completed','response':response([message(output)])}]),
               ('ollama',dict(MODEL,url='http://localhost:11434',stream=True),[{'message':{'role':'assistant','content':output},'done':True}])]
        for name,connection,reply in cases:
            with self.subTest(protocol=name),tempfile.TemporaryDirectory() as root:
                Path(root,'spec.md').write_text('SPEC',encoding='utf-8')
                run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':connection});events=[]
                def send(selected,url,body,timeout):
                    if name!='ollama':return Wire(reply)
                    wire=io.BytesIO(('\n'.join(json.dumps(item) for item in reply)+'\n').encode());wire.headers={'Content-Type':'application/x-ndjson'};return wire
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
                with patch.object(core,'open_request',side_effect=send) as transport:run.run(emit)
                self.assertEqual(transport.call_count,1)
                result=next(e['review'] for e in events if e['kind']=='independent_review_result' and e['review']['pass_status']!='pending')
                self.assertEqual(result['pass_status'],'completed',events);self.assertEqual(result['structured']['status'],'valid',events)

    def test_protocol_transport_parses_complete_results_and_discards_incomplete_results(self):
        finding={'version':1,'findings':[{'severity':'low','title':'Review item','rationale':'Inspect this','location':'','assumptions':'','verification':''}]}
        output=json.dumps(finding)
        cases=[('chat',MODEL,lambda complete:chat(output,finish='stop' if complete else None)),
               ('messages',dict(MODEL,protocol='messages'),lambda complete:msg([{'type':'text','text':output}],stop='end_turn' if complete else None)),
               ('responses',dict(MODEL,protocol='responses'),lambda complete:response([message(output)],status='completed' if complete else 'in_progress')),
               ('ollama',dict(MODEL,url='http://localhost:11434'),lambda complete:{'message':{'role':'assistant','content':output},'done':complete})]
        for name,connection,reply in cases:
            for complete in (True,False):
                with self.subTest(protocol=name,complete=complete),tempfile.TemporaryDirectory() as root:
                    Path(root,'spec.md').write_text('SPEC',encoding='utf-8')
                    run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':connection});events=[];requests=[]
                    def send(selected,url,body,timeout):
                        requests.append((url,copy.deepcopy(body)))
                        return Wire(reply(complete),False)
                    def emit(event):
                        events.append(event)
                        if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
                    with patch.object(core,'open_request',side_effect=send):run.run(emit)
                    self.assertEqual(len(requests),1,events)
                    proposal=next(e['proposal'] for e in events if e['kind']=='operation_proposal')
                    url,body=requests[0];self.assertEqual(url,proposal['destination'])
                    self.assertEqual(body['input' if name=='responses' else 'messages'][0]['content'],proposal['diff'])
                    self.assertNotIn('tools',body)
                    result=next(e['review'] for e in events if e['kind']=='independent_review_result' and e['review']['pass_status']!='pending')
                    self.assertEqual(result['pass_status'],'completed' if complete else 'failed',events)
                    self.assertEqual(len(result['structured']['findings']),int(complete),events)
                    if complete:self.assertEqual(result['structured']['findings'][0]['title'],'Review item')

    def test_protocol_adapters_receive_only_the_approved_fresh_input(self):
        from agentnik import compat_tools, ollama_tools, responses_tools
        cases=[('chat',MODEL,compat_tools),('messages',dict(MODEL,protocol='messages'),compat_tools),
               ('responses',dict(MODEL,protocol='responses'),responses_tools),
               ('ollama',dict(MODEL,url='http://localhost:11434',protocol='chat'),ollama_tools)]
        for name,connection,adapter in cases:
            with self.subTest(protocol=name),tempfile.TemporaryDirectory() as root:
                Path(root,'spec.md').write_text('SPEC private-key',encoding='utf-8')
                Path(root,'evidence.txt').write_text('SELECTED EVIDENCE',encoding='utf-8')
                Path(root,'AGENTS.md').write_text('PRIVATE GUIDANCE',encoding='utf-8')
                Path(root,'unselected.txt').write_text('PRIVATE UNSELECTED',encoding='utf-8')
                run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':['evidence.txt']}],{'light':dict(connection,api_key='private-key')})
                events=[];requests=[]
                def request(selected,body,runtime,emit,state):
                    requests.append((copy.deepcopy(selected),copy.deepcopy(body)))
                    state.update(text='{"version":1,"findings":[]}',metrics={'input_tokens':12,'output_tokens':4})
                    return {},[]
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
                with patch.object(adapter,'request',side_effect=request),patch.object(core,'open_request') as network:
                    run.run(emit)
                network.assert_not_called();self.assertEqual(len(requests),1,events)
                selected,body=requests[0];proposal=next(e['proposal'] for e in events if e['kind']=='operation_proposal')
                messages=body['input' if name=='responses' else 'messages']
                self.assertEqual(len(messages),1);self.assertEqual(messages[0]['role'],'user')
                self.assertEqual(messages[0]['content'],proposal['diff']);self.assertEqual(selected['model'],'reviewer')
                self.assertIn('SELECTED EVIDENCE',messages[0]['content']);self.assertNotIn('tools',body)
                for private in ('private-key','PRIVATE GUIDANCE','PRIVATE UNSELECTED'):
                    self.assertNotIn(private,json.dumps(body));self.assertNotIn(private,json.dumps(events))
                if name=='responses':self.assertIs(body['store'],False)
                self.assertTrue(any(e['kind']=='independent_review_result' and e['review']['pass_status']=='completed' for e in events),events)

    def test_direct_review_rejects_unavailable_tool_calls_without_retry(self):
        from agentnik import compat_tools
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8')
            run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':MODEL});events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(compat_tools,'request',return_value=({},[object()])) as request,patch.object(core,'open_request') as network:
                run.run(emit)
            self.assertEqual(request.call_count,1);network.assert_not_called()
            self.assertTrue(any(e['kind']=='independent_review_result' and e['review']['pass_status']=='failed' and not e['review']['structured']['findings'] for e in events),events)

    def test_heavy_review_progress_is_saved_before_children_and_on_completion(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.storage import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();(project/'spec.md').write_text('SPEC',encoding='utf-8');store=Store(Path(root)/'data');window=Window(store);started=threading.Event();release=threading.Event();count=[0]
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                window.connections['Heavy']=dict(MODEL,model='heavy');window.connections['Review']=dict(MODEL)
                for role,name,alias in [('heavy','Heavy','heavy'),('light','Review','reviewer')]:
                    box,model=tab.roles[role];box.addItem(name,name);box.setCurrentIndex(box.findData(name));model.setText(alias)
                tab.light_enabled.setChecked(True);tab.save_review_progress.setChecked(True);tab.composer.setPlainText('Review the document')
                def send(connection,url,body,timeout):
                    if connection['model']=='reviewer':started.set();release.wait(5);return Wire(chat('{"version":1,"findings":[]}'),False)
                    count[0]+=1
                    if count[0]==1:
                        passes=[{'role':'comprehension','model':'light','paths':[]},{'role':'design','model':'light','paths':[]}]
                        from test_code_agent import call
                        return Wire(chat(calls=[call('review_document_parallel',{'path':'spec.md','passes':json.dumps(passes)})],finish='tool_calls'),False)
                    return Wire(chat('Done'),False)
                with patch.object(core,'open_request',side_effect=send):
                    tab.start_coding();deadline=time.monotonic()+5
                    while not started.is_set() and time.monotonic()<deadline:
                        app.processEvents()
                        if tab.pending_fingerprint:tab.decide(True)
                        time.sleep(.01)
                    self.assertTrue(started.is_set());saved=next(row for row in store.list_sessions() if row['id']==session['id'])
                    self.assertEqual([item['pass_status'] for item in saved['coding_review_history'][0]['reviews']],['interrupted','interrupted'])
                    release.set();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
                    app.processEvents()
                self.assertIsNone(tab.job);saved=next(row for row in store.list_sessions() if row['id']==session['id']);self.assertEqual([item['pass_status'] for item in saved['coding_review_history'][0]['reviews']],['completed','completed'])
                with patch.object(core,'open_request') as request:window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents();request.assert_not_called()
            finally:release.set();window.close();app.processEvents();store.db.close()

    def test_opt_in_progress_requires_manifest_ack_before_network(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8')
            for saved in (True,False):
                with self.subTest(saved=saved):
                    run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':MODEL},save_progress=True);events=[];manifests=[]
                    def emit(event):
                        events.append(event)
                        if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
                        if event['kind']=='independent_review_manifest':manifests.append(event['reviews']);run.acknowledge_manifest(saved)
                    with patch.object(core,'open_request',return_value=Wire(chat('{"version":1,"findings":[]}'),False)) as send:run.run(emit)
                    self.assertEqual(send.call_count,int(saved));self.assertEqual(len(manifests),1);self.assertEqual(manifests[0][0]['pass_status'],'pending')
                    self.assertEqual(events[-1]['status'],'completed' if saved else 'failed')
                    if not saved:self.assertIn('no reviewer requests were sent',events[-1]['text'])

    def test_direct_run_approves_each_pass_and_sends_only_snapshots(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8');Path(root,'evidence.txt').write_text('EVIDENCE',encoding='utf-8')
            definitions=[{'role':'comprehension','model':'light','paths':[]},{'role':'design','model':'light','paths':['evidence.txt']}]
            run=DirectReviewRun(root,'spec.md',definitions,{'light':MODEL});events=[];bodies=[]
            def send(connection,url,body,timeout):bodies.append(copy.deepcopy(body));return Wire(chat('{"version":1,"findings":[]}'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(len(bodies),2)
            approvals=[event['proposal'] for event in events if event['kind']=='operation_proposal'];self.assertEqual(len(approvals),2)
            for body,proposal in zip(bodies,approvals):
                self.assertEqual(body['messages'][0]['content'],proposal['diff']);self.assertNotIn('tools',body)
            self.assertNotIn('EVIDENCE',bodies[0]['messages'][0]['content']);self.assertIn('EVIDENCE',bodies[1]['messages'][0]['content'])
            self.assertEqual(sum(event['kind']=='independent_review_result' and event['review']['pass_status']=='completed' for event in events),2)

    def test_each_direct_pass_receives_only_its_selected_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8');Path(root,'one.txt').write_text('FIRST EVIDENCE',encoding='utf-8');Path(root,'two.txt').write_text('SECOND EVIDENCE',encoding='utf-8')
            definitions=[{'role':'design','model':'light','paths':['one.txt']},{'role':'readiness','model':'light','paths':['two.txt']}]
            run=DirectReviewRun(root,'spec.md',definitions,{'light':MODEL});events=[];bodies=[]
            def send(connection,url,body,timeout):bodies.append(copy.deepcopy(body));return Wire(chat('{"version":1,"findings":[]}'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(len(bodies),2)
            self.assertIn('FIRST EVIDENCE',json.dumps(bodies[0]));self.assertNotIn('SECOND EVIDENCE',json.dumps(bodies[0]))
            self.assertIn('SECOND EVIDENCE',json.dumps(bodies[1]));self.assertNotIn('FIRST EVIDENCE',json.dumps(bodies[1]))

    def test_drift_check_is_approved_read_only_and_requires_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            spec=Path(root,'spec.md');code=Path(root,'implementation.py');spec.write_text('SPEC REQUIREMENT',encoding='utf-8');code.write_text('CODE SNAPSHOT',encoding='utf-8')
            with self.assertRaises(ValueError):DirectReviewRun(root,'spec.md',[{'role':'drift','model':'light','paths':[]}],{'light':MODEL})
            run=DirectReviewRun(root,'spec.md',[{'role':'drift','model':'light','paths':['implementation.py']}],{'light':MODEL});events=[];bodies=[]
            def send(connection,url,body,timeout):bodies.append(copy.deepcopy(body));return Wire(chat('{"version":1,"findings":[]}'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(len(bodies),1)
            proposal=next(event['proposal'] for event in events if event['kind']=='operation_proposal');payload=bodies[0]['messages'][0]['content']
            self.assertEqual(proposal['role'],'drift');self.assertEqual(payload,proposal['diff']);self.assertIn('SPEC REQUIREMENT',payload);self.assertIn('CODE SNAPSHOT',payload);self.assertIn('not proof of consistency',payload);self.assertNotIn('tools',bodies[0])
            self.assertEqual(spec.read_text(encoding='utf-8'),'SPEC REQUIREMENT');self.assertEqual(code.read_text(encoding='utf-8'),'CODE SNAPSHOT')
            self.assertTrue(any(event['kind']=='independent_review_result' and event['review']['role']=='drift' and event['review']['pass_status']=='completed' for event in events))

    def test_repository_fit_pass_uses_only_approved_project_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'proposal.md').write_text('PROPOSAL',encoding='utf-8');Path(root,'api.py').write_text('API EVIDENCE',encoding='utf-8');Path(root,'not_selected.py').write_text('PRIVATE UNSELECTED',encoding='utf-8')
            with self.assertRaises(ValueError):DirectReviewRun(root,'proposal.md',[{'role':'repository_fit','model':'light','paths':[]}],{'light':MODEL})
            run=DirectReviewRun(root,'proposal.md',[{'role':'repository_fit','model':'light','paths':['api.py']}],{'light':MODEL});events=[];bodies=[]
            def send(connection,url,body,timeout):bodies.append(copy.deepcopy(body));return Wire(chat('{"version":1,"findings":[]}'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events);proposal=next(event['proposal'] for event in events if event['kind']=='operation_proposal');payload=bodies[0]['messages'][0]['content']
            self.assertEqual(proposal['role'],'repository_fit');self.assertEqual(payload,proposal['diff']);self.assertIn('PROPOSAL',payload);self.assertIn('API EVIDENCE',payload);self.assertNotIn('PRIVATE UNSELECTED',payload);self.assertIn('not proof of compatibility',payload);self.assertNotIn('tools',bodies[0])
            self.assertTrue(any(event['kind']=='independent_review_result' and event['review']['role']=='repository_fit' and event['review']['pass_status']=='completed' for event in events))

    def test_rejection_never_sends(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8')
            run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':MODEL});events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],False)
            with patch.object(core,'open_request') as send:run.run(emit)
            send.assert_not_called();self.assertEqual(events[-1]['status'],'failed');self.assertIn('rejected',events[-1]['text'])

    def test_direct_review_discards_output_exceeding_shared_context(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8');limits=coding_limits();limits['context_bytes']=4096
            run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':MODEL},limits=limits);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',return_value=Wire(chat('X'*4000),False)):run.run(emit)
            record=next(event['review'] for event in events if event['kind']=='independent_review_result' and event['review']['pass_status']!='pending')
            self.assertEqual(record['pass_status'],'failed');self.assertEqual(record['structured']['findings'],[])
            self.assertTrue(any('remaining context budget' in event.get('text','') for event in events));self.assertNotIn('X'*100,json.dumps(events))

    def test_individual_cancel_discards_late_result(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('SPEC',encoding='utf-8');run=DirectReviewRun(root,'spec.md',[{'role':'design','model':'light','paths':[]}],{'light':MODEL});events=[];started=threading.Event();release=threading.Event();ids=[]
            def send(connection,url,body,timeout):started.set();release.wait(5);return Wire(chat('LATE FINDING'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
                if event['kind']=='subagent' and event['subagent']['status']=='running':ids.append(event['subagent']['id'])
            with patch.object(core,'open_request',side_effect=send):
                thread=threading.Thread(target=run.run,args=(emit,));thread.start()
                try:
                    self.assertTrue(started.wait(3));self.assertTrue(run.cancel_subagent(ids[0]));thread.join(3);self.assertFalse(thread.is_alive())
                finally:release.set();thread.join(3)
            self.assertTrue(any(event['kind']=='independent_review_result' and event['review']['pass_status']=='cancelled' for event in events));self.assertNotIn('LATE FINDING',json.dumps(events))

    def test_opted_in_progress_is_saved_before_request_and_reopens_interrupted(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from agentnik.ui import Window
        from agentnik.code_ui import DirectReviewDialog
        from agentnik.storage import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();(project/'spec.md').write_text('SPEC',encoding='utf-8');store=Store(Path(root)/'data');window=Window(store);release=threading.Event();started=threading.Event()
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                window.connections['Review']=dict(MODEL);box,model=tab.roles['light'];box.addItem('Review','Review');box.setCurrentIndex(box.findData('Review'));model.setText('reviewer');tab.light_enabled.setChecked(True)
                def configure(dialog):dialog.target.setText('spec.md');dialog.save_progress.setChecked(True);return QDialog.DialogCode.Accepted
                def send(connection,url,body,timeout):started.set();release.wait(5);return Wire(chat('late'),False)
                with patch.object(DirectReviewDialog,'exec',configure),patch.object(core,'open_request',side_effect=send):
                    tab.start_direct_review();deadline=time.monotonic()+5
                    while not started.is_set() and time.monotonic()<deadline:
                        app.processEvents()
                        if tab.pending_fingerprint:tab.decide(True)
                        time.sleep(.01)
                    self.assertTrue(started.is_set())
                    saved=next(row for row in store.list_sessions() if row['id']==session['id']);self.assertEqual(saved['coding_review_history'][0]['reviews'][0]['pass_status'],'interrupted')
                    tab.cancel();release.set();app.processEvents()
                saved=next(row for row in store.list_sessions() if row['id']==session['id']);self.assertEqual(saved['coding_review_history'][0]['reviews'][0]['pass_status'],'interrupted')
                with patch.object(core,'open_request') as send_again:window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents();send_again.assert_not_called()
                self.assertTrue(window.tabs.currentWidget().saved_reviews_button.isEnabled())
            finally:release.set();window.close();app.processEvents();store.db.close()

    def test_progress_storage_failure_prevents_reviewer_request(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from agentnik.ui import Window
        from agentnik.code_ui import DirectReviewDialog
        from agentnik.storage import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();(project/'spec.md').write_text('SPEC',encoding='utf-8');store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                window.connections['Review']=dict(MODEL);box,model=tab.roles['light'];box.addItem('Review','Review');box.setCurrentIndex(box.findData('Review'));model.setText('reviewer');tab.light_enabled.setChecked(True)
                def configure(dialog):dialog.target.setText('spec.md');dialog.save_progress.setChecked(True);return QDialog.DialogCode.Accepted
                original=store.save
                def save(value):
                    if value.get('coding_review_history'):raise OSError('simulated storage failure')
                    return original(value)
                with patch.object(DirectReviewDialog,'exec',configure),patch.object(store,'save',side_effect=save),patch.object(core,'open_request') as request:
                    tab.start_direct_review();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:
                        app.processEvents()
                        if tab.pending_fingerprint:tab.decide(True)
                        time.sleep(.01)
                    app.processEvents();request.assert_not_called()
                self.assertIsNone(tab.job);self.assertIn('no reviewer requests were sent',tab.activity.toPlainText());self.assertFalse(session.get('coding_review_history'))
            finally:window.close();app.processEvents();store.db.close()

    def test_terminal_progress_save_failure_keeps_interrupted_snapshot(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from agentnik.ui import Window
        from agentnik.code_ui import DirectReviewDialog
        from agentnik.storage import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();(project/'spec.md').write_text('SPEC',encoding='utf-8');store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                window.connections['Review']=dict(MODEL);box,model=tab.roles['light'];box.addItem('Review','Review');box.setCurrentIndex(box.findData('Review'));model.setText('reviewer');tab.light_enabled.setChecked(True)
                def configure(dialog):dialog.target.setText('spec.md');dialog.save_progress.setChecked(True);return QDialog.DialogCode.Accepted
                original=store.save
                def save(value):
                    if any(review.get('pass_status')=='completed' for snapshot in value.get('coding_review_history',[]) for review in snapshot['reviews']):raise OSError('simulated storage failure')
                    return original(value)
                with patch.object(DirectReviewDialog,'exec',configure),patch.object(store,'save',side_effect=save),patch.object(core,'open_request',return_value=Wire(chat('{"version":1,"findings":[]}'),False)) as request:
                    tab.start_direct_review();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:
                        app.processEvents()
                        if tab.pending_fingerprint:tab.decide(True)
                        time.sleep(.01)
                    app.processEvents();self.assertEqual(request.call_count,1)
                self.assertIsNone(tab.job);self.assertIn('could not be saved',tab.activity.toPlainText());saved=next(row for row in store.list_sessions() if row['id']==session['id']);self.assertEqual(saved['coding_review_history'][0]['reviews'][0]['pass_status'],'interrupted')
            finally:window.close();app.processEvents();store.db.close()

    def test_offscreen_dialog_configures_direct_run_without_heavy(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from agentnik.ui import Window
        from agentnik.code_ui import DirectReviewDialog
        from agentnik.storage import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();(project/'spec.md').write_text('SPEC',encoding='utf-8');store=Store(Path(root)/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                window.connections['Review']=dict(MODEL);box,model=tab.roles['light'];box.addItem('Review','Review');box.setCurrentIndex(box.findData('Review'));model.setText('reviewer');tab.light_enabled.setChecked(True)
                def configure(dialog):
                    dialog.target.setText('spec.md');dialog.passes[0][0].setCurrentIndex(dialog.passes[0][0].findData('design'));return QDialog.DialogCode.Accepted
                with patch.object(DirectReviewDialog,'exec',configure),patch.object(tab,'launch') as launch:
                    tab.start_direct_review();launch.assert_called_once();run=launch.call_args.args[0]
                self.assertIsInstance(run,DirectReviewRun);self.assertEqual(run.target,'spec.md');self.assertEqual(run.definitions[0]['role'],'design')
                session['coding_context']={'task':'Earlier task','answer':'Earlier answer'};session['coding_plan']={'explanation':'Prior plan','steps':[{'step':'Keep','status':'pending'}]};tab.composer.setPlainText('Unsent draft')
                def send(connection,url,body,timeout):return Wire(chat('{"version":1,"findings":[]}'),False)
                with patch.object(DirectReviewDialog,'exec',configure),patch.object(core,'open_request',side_effect=send) as request:
                    tab.start_direct_review();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:
                        app.processEvents()
                        if tab.pending_fingerprint:tab.decide(True)
                        time.sleep(.01)
                    app.processEvents()
                self.assertIsNone(tab.job);self.assertEqual(request.call_count,1);self.assertEqual(session['coding_context']['task'],'Earlier task');self.assertEqual(session['coding_plan']['steps'][0]['step'],'Keep');self.assertEqual(tab.composer.toPlainText(),'Unsent draft');self.assertTrue(tab.review_results)
                (project/'code.py').write_text('CODE',encoding='utf-8')
                window.connections['Review']=dict(MODEL);box,model=tab.roles['light']
                if box.findData('Review')<0:box.addItem('Review','Review')
                box.setCurrentIndex(box.findData('Review'));model.setText('reviewer')
                def configure_drift(dialog):
                    dialog.target.setText('spec.md');dialog.passes[0][0].setCurrentIndex(dialog.passes[0][0].findData('drift'));dialog.evidence_fields[0].setPlainText('code.py');dialog.save_progress.setChecked(True);return QDialog.DialogCode.Accepted
                with patch.object(DirectReviewDialog,'exec',configure_drift),patch.object(core,'open_request',side_effect=send),patch('agentnik.code_ui.QMessageBox.warning') as warning:
                    tab.start_direct_review();deadline=time.monotonic()+5
                    while tab.job and time.monotonic()<deadline:
                        app.processEvents()
                        if tab.pending_fingerprint:tab.decide(True)
                        time.sleep(.01)
                    app.processEvents()
                warning.assert_not_called();self.assertIsNone(tab.job);self.assertTrue(tab.review_results,warning.call_args);self.assertEqual(next(iter(tab.review_results.values()))['role'],'drift')
                saved=next(row for row in store.list_sessions() if row['id']==session['id']);history=saved['coding_review_history'];self.assertEqual(len(history),1);self.assertEqual(history[0]['reviews'][0]['role'],'drift');self.assertEqual(history[0]['reviews'][0]['pass_status'],'completed')
                with patch.object(core,'open_request') as request:
                    window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents();request.assert_not_called()
                self.assertTrue(window.tabs.currentWidget().saved_reviews_button.isEnabled())
            finally:window.close();app.processEvents();store.db.close()

    def test_dialog_evidence_is_per_pass_and_comprehension_is_document_only(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.code_ui import DirectReviewDialog
        app=QApplication.instance() or QApplication([]);dialog=DirectReviewDialog(None,{'light':MODEL},'spec.md')
        try:
            first=dialog.passes[0][0];second=dialog.passes[1][0];third=dialog.passes[2][0]
            self.assertFalse(dialog.evidence_fields[0].isEnabled())
            first.setCurrentIndex(first.findData('design'));dialog.evidence_fields[0].setPlainText('one.txt\ntwo.txt')
            second.setCurrentIndex(second.findData('readiness'));dialog.evidence_fields[1].setPlainText('other.txt')
            third.setCurrentIndex(third.findData('comprehension'));self.assertFalse(dialog.evidence_fields[2].isEnabled())
            target,passes=dialog.values();self.assertEqual(target,'spec.md');self.assertEqual([item['paths'] for item in passes],[['one.txt','two.txt'],['other.txt'],[]])
            third.setCurrentIndex(third.findData('drift'))
            with self.assertRaises(ValueError):dialog.values()
            dialog.evidence_fields[2].setPlainText('source.py');self.assertEqual(dialog.values()[1][2]['paths'],['source.py'])
            third.setCurrentIndex(third.findData('repository_fit'));dialog.evidence_fields[2].clear()
            with self.assertRaises(ValueError):dialog.values()
            dialog.evidence_fields[2].setPlainText('interfaces.py');self.assertEqual(dialog.values()[1][2]['role'],'repository_fit')
            dialog.evidence_fields[1].setPlainText('same.txt\nsame.txt')
            with self.assertRaises(ValueError):dialog.values()
            with patch('agentnik.code_ui.QMessageBox.warning') as warning,patch.object(dialog,'accept') as accept:
                dialog.validate_and_accept();warning.assert_called_once();accept.assert_not_called();self.assertEqual(dialog.evidence_fields[1].toPlainText(),'same.txt\nsame.txt')
            dialog.evidence_fields[1].setPlainText('one\ntwo\nthree\nfour')
            with self.assertRaises(ValueError):dialog.values()
        finally:dialog.close();app.processEvents()

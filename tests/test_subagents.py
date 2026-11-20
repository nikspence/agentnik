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
    def test_same_model_inspection_is_confined_to_approved_snapshots(self):
        from agentnik import compat_tools
        from agentnik.tools import ToolCall
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);(base/'approved.py').write_text('alpha\nFIND THIS\n',encoding='utf-8');(base/'private.py').write_text('private-marker',encoding='utf-8')
            events=[];child_bodies=[];parent_count=[0];lock=threading.Lock();run=CodingRun(dict(C,stream=False),root,'Review')
            tasks=[{'task':'Inspect','paths':['approved.py'],'inspect':True},'Other']
            def request(connection,body,runtime,emit,state,*args,**kwargs):
                text=json.dumps(body)
                if 'Independent read-only coding analysis.' not in text:
                    parent_count[0]+=1
                    if parent_count[0]==1:return {'role':'assistant','content':'','tool_calls':[]},[ToolCall('delegate','delegate_subagents',{'tasks':json.dumps(tasks)})]
                    state['text']='Done';return {'role':'assistant','content':'Done'},[]
                if 'Task: Other' in text:state['text']='Other';return {'role':'assistant','content':'Other'},[]
                with lock:child_bodies.append(copy.deepcopy(body));index=len(child_bodies)
                if index==1:
                    calls=[ToolCall('one','glob_files',{'pattern':'**/*.py'}),ToolCall('two','grep_files',{'pattern':'**/*.py','query':'find','case_sensitive':'false'}),ToolCall('three','read_file',{'path':'approved.py'}),ToolCall('four','read_file',{'path':'private.py'})]
                    return {'role':'assistant','content':''},calls
                state['text']='Inspected';return {'role':'assistant','content':'Inspected'},[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(compat_tools,'request',side_effect=request):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(len(child_bodies),2)
            payload=json.dumps(child_bodies[1]);self.assertIn('FIND THIS',payload);self.assertIn('outside the approved snapshots',payload);self.assertNotIn('private-marker',payload)
            self.assertEqual(len([event for event in events if event['kind']=='operation_proposal']),1)

    def test_same_model_subagent_file_transfer_requires_approval(self):
        for approve in (False,True):
            with self.subTest(approve=approve),tempfile.TemporaryDirectory() as root:
                Path(root,'a.txt').write_text('project evidence',encoding='utf-8');events=[];bodies=[];lock=threading.Lock()
                run=CodingRun(dict(C,stream=False),root,'Analyze')
                def send(connection,url,body,timeout):
                    with lock:bodies.append(copy.deepcopy(body))
                    if 'Independent read-only coding analysis.' in json.dumps(body):return Wire(chat('Finding'),False)
                    if len([b for b in bodies if 'Independent read-only coding analysis.' not in json.dumps(b)])==1:
                        tasks=[{'task':'Inspect','paths':['a.txt']},'Other']
                        return Wire(chat(calls=[call('delegate_subagents',{'tasks':json.dumps(tasks)})],finish='tool_calls'),False)
                    return Wire(chat('Done'),False)
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':run.decide(event['fingerprint'],approve)
                with patch.object(core,'open_request',side_effect=send):run.run(emit)
                self.assertEqual(events[-1]['status'],'completed',events)
                children=[body for body in bodies if 'Independent read-only coding analysis.' in json.dumps(body)]
                self.assertEqual(len(children),2 if approve else 0)
                if approve:self.assertTrue(any('project evidence' in json.dumps(body) for body in children))

    def test_same_model_subagents_respect_shared_request_budget(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as root:
            limits=coding_limits();limits['requests']=2;events=[];bodies=[]
            run=CodingRun(dict(C,stream=False),root,'Analyze',limits=limits)
            def send(connection,url,body,timeout):
                bodies.append(body);return Wire(chat(calls=[call('delegate_subagents',{'tasks':json.dumps(['one','two'])})],finish='tool_calls'),False)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(len(bodies),1);self.assertEqual(events[-1]['status'],'failed');self.assertTrue(events[-1]['limited'])

    def test_same_model_subagent_cancellation_drops_late_output(self):
        with tempfile.TemporaryDirectory() as root:
            started=threading.Event();release=threading.Event();events=[];lock=threading.Lock();count=[0]
            run=CodingRun(dict(C,stream=False),root,'Analyze')
            def send(connection,url,body,timeout):
                if 'Independent read-only coding analysis.' in json.dumps(body):
                    with lock:
                        count[0]+=1
                        if count[0]==2:started.set()
                    release.wait(5);return Wire(chat('Late finding'),False)
                return Wire(chat(calls=[call('delegate_subagents',{'tasks':json.dumps(['one','two'])})],finish='tool_calls'),False)
            with patch.object(core,'open_request',side_effect=send):
                worker=threading.Thread(target=run.run,args=(events.append,));worker.start()
                try:self.assertTrue(started.wait(3));run.stop()
                finally:release.set();worker.join(5)
            self.assertFalse(worker.is_alive());self.assertNotIn('Late finding',json.dumps(events))

    def test_subagents_use_parent_connection_without_light_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'AGENTS.md').write_text('Use project naming.',encoding='utf-8')
            events=[];requests=[];parent_requests=0;lock=threading.Lock()
            run=CodingRun(dict(C,stream=False,api_key='parent-key'),root,'Analyze')
            def send(connection,url,body,timeout):
                nonlocal parent_requests
                with lock:requests.append((dict(connection),copy.deepcopy(body)))
                messages=body.get('messages',[])
                if any('Independent read-only coding analysis.' in str(message.get('content','')) for message in messages):
                    return Wire(chat('Finding'),False)
                parent_requests+=1
                if parent_requests==1:return Wire(chat(calls=[call('delegate_subagents',{'tasks':json.dumps(['first','second'])})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events)
            self.assertEqual(len(requests),4)
            self.assertTrue(all(request[0]['model']==C['model'] and request[0]['api_key']=='parent-key' for request in requests))
            children=[body for _,body in requests if 'Independent read-only coding analysis.' in json.dumps(body)]
            self.assertEqual(len(children),2);self.assertTrue(all('Use project naming.' in json.dumps(body) for body in children))
            self.assertIn('Subagent: 2 request(s)',run.usage_text())
            self.assertTrue(any(tool.get('function',{}).get('name')=='delegate_subagents' for tool in requests[0][1]['tools']))
            self.assertFalse({tool.get('function',{}).get('name') for tool in requests[0][1]['tools']} & {'delegate_light','delegate_parallel','review_document','review_document_role','review_document_evidence','review_document_structured','review_document_parallel'})

    def test_subagents_reject_alternate_model_selection(self):
        with tempfile.TemporaryDirectory() as root:
            events=[];requests=[];bodies=[];parent_requests=0
            run=CodingRun(dict(C,stream=False),root,'Analyze',light=dict(C,model='light',stream=False),alternate=dict(C,model='alternate',stream=False))
            def send(connection,url,body,timeout):
                nonlocal parent_requests
                requests.append(connection['model']);bodies.append(copy.deepcopy(body));parent_requests+=1
                if parent_requests==1:return Wire(chat(calls=[call('delegate_subagents',{'tasks':json.dumps(['first',{'task':'second','model':'alternate'}])})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events)
            self.assertEqual(requests,[C['model'],C['model']]);self.assertIn('omit the model field',json.dumps(bodies[-1]))































    def test_modified_selected_skill_invalidates_pending_approval(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'.agents/skills/review';folder.mkdir(parents=True)
            skill=folder/'SKILL.md';skill.write_text('---\nname: review\ndescription: Review\n---\nOriginal',encoding='utf-8')
            run=CodingRun(dict(C,stream=False),root,'Create folder',skills=['review']);events=[]
            def emit(event):
                events.append(event)
                if event.get('text','').startswith('Applying project create_directory:'):
                    skill.write_text('---\nname: review\ndescription: Review\n---\nChanged',encoding='utf-8')
            replies=[Wire(chat(calls=[call('create_directory',{'path':'new'})],finish='tool_calls'),False)]
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertFalse((Path(root)/'new').exists());self.assertEqual(events[-1]['status'],'failed');self.assertIn('skill changed',events[-1]['text'].lower())




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

    def test_skill_removal_during_request_stops_before_file_tool(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'.agents/skills/review';folder.mkdir(parents=True)
            skill=folder/'SKILL.md';skill.write_text('---\nname: review\ndescription: Review\n---\nOriginal',encoding='utf-8')
            events=[];requests=[]
            def send(c,url,body,timeout):
                requests.append(body);skill.unlink()
                return Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'should not be written'})],finish='tool_calls'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Create a file',skills=['review']).run(events.append)
            self.assertEqual(len(requests),1);self.assertFalse((Path(root)/'new.txt').exists())
            self.assertEqual(events[-1]['status'],'failed');self.assertIn('unavailable',events[-1]['text'].lower())

    def test_skill_reference_change_or_removal_stops_before_file_tool(self):
        for removed in (False,True):
            with self.subTest(removed=removed),tempfile.TemporaryDirectory() as root:
                folder=Path(root)/'.agents/skills/review';folder.mkdir(parents=True)
                (folder/'SKILL.md').write_text('---\nname: review\ndescription: Review\n---\nRead reference',encoding='utf-8')
                reference=folder/'reference.md';reference.write_text('Original',encoding='utf-8')
                events=[];requests=[]
                def send(c,url,body,timeout):
                    requests.append(copy.deepcopy(body))
                    if len(requests)==1:return Wire(chat(calls=[call('read_skill_resource',{'name':'review','path':'reference.md'})],finish='tool_calls'),False)
                    if removed:reference.unlink()
                    else:reference.write_text('Updated',encoding='utf-8')
                    return Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'should not be written'})],finish='tool_calls'),False)
                with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Create a file',skills=['review']).run(events.append)
                self.assertEqual(len(requests),2);self.assertIn('Original',json.dumps(requests[1]));self.assertFalse((Path(root)/'new.txt').exists())
                self.assertEqual(events[-1]['status'],'failed');self.assertIn('skill reference',events[-1]['text'].lower())

    def test_unchanged_skill_reference_allows_follow_up(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'.agents/skills/review';folder.mkdir(parents=True)
            (folder/'SKILL.md').write_text('---\nname: review\ndescription: Review\n---\nRead reference',encoding='utf-8')
            (folder/'reference.md').write_text('Original',encoding='utf-8');events=[];requests=[]
            def send(c,url,body,timeout):
                requests.append(body)
                if len(requests)==1:return Wire(chat(calls=[call('read_skill_resource',{'name':'review','path':'reference.md'})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Review',skills=['review']).run(events.append)
            self.assertEqual(len(requests),2);self.assertEqual(events[-1]['status'],'completed')




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
                proposal.update(operation='independent_review',role='design',diff='Fixed instructions\nDocument contents')
                proposal['target_payload_sha256']='e'*64
                proposal['evidence']=[{'path':'evidence.txt','sha256':'c'*64,'payload_sha256':'d'*64}]
                tab.receive({'kind':'operation_proposal','run_id':'active','fingerprint':'g','proposal':proposal})
                self.assertIn('INDEPENDENT DOCUMENT REVIEW',tab.approval.toPlainText());self.assertIn('design',tab.approval.toPlainText());self.assertIn('a'*64,tab.approval.toPlainText());self.assertIn('b'*64,tab.approval.toPlainText())
                self.assertIn('evidence.txt',tab.approval.toPlainText());self.assertIn('c'*64,tab.approval.toPlainText());self.assertIn('d'*64,tab.approval.toPlainText())
                self.assertIn('Transmitted document text SHA-256',tab.approval.toPlainText());self.assertIn('e'*64,tab.approval.toPlainText())
                self.assertIn('other secrets may remain',tab.approval.toPlainText());self.assertIn('retain the input or charge',tab.approval.toPlainText())
                self.assertEqual(tab.diff.toPlainText(),'Fixed instructions\nDocument contents');self.assertFalse(tab.diff.isHidden())
            finally:
                if window.tabs.currentWidget():window.tabs.currentWidget().job=None
                window.close();app.processEvents();store.db.close()




    def test_code_pane_remembers_rejection_for_next_run_and_can_clear_it(self):
        import os
        from PySide6.QtWidgets import QApplication
        from agentnik.storage import Store,load_config
        from agentnik.subagent_capabilities import unsupported
        from agentnik.ui import Window
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();store=Store(Path(root)/'data')
            store.config['connections']={'Primary':{'url':'https://example.com/v1','protocol':'chat','model':'base'}}
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                for role in ('heavy',):
                    combo,model=tab.roles[role];combo.setCurrentIndex(combo.findData('Primary'));model.setText(role)
                tab.composer.setPlainText('Review');tab.save_models()
                with patch.object(tab,'launch') as launch:
                    tab.start_coding();run=launch.call_args.args[0]
                self.assertEqual(run.unsupported_subagent_roles,set());tab.job=run;tab.run_id=run.run_id
                tab.receive({'run_id':run.run_id,'kind':'subagent_tools_unsupported','role':'model'})
                self.assertTrue(unsupported(load_config(store.config_path),tab.role_connection('heavy')))
                self.assertIn('_capability_scope',store.config['connections']['Primary']);tab.job=None
                with patch.object(tab,'launch') as launch:
                    tab.start_coding();self.assertEqual(launch.call_args.args[0].unsupported_subagent_roles,{'model'})
                tab.forget_subagent_capabilities();self.assertFalse(unsupported(load_config(store.config_path),tab.role_connection('heavy')))
                with patch.object(tab,'launch') as launch:
                    tab.start_coding();self.assertEqual(launch.call_args.args[0].unsupported_subagent_roles,set())
            finally:tab.job=None;window.close();app.processEvents();store.db.close()


    def test_remembered_subagent_capability_persists_and_invalidates(self):
        from agentnik.storage import Store,load_config
        from agentnik.subagent_capabilities import remember,unsupported
        from agentnik.research_settings import invalidate_capabilities
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);connection={'url':'https://example.com/v1','protocol':'chat','model':'small','_capability_scope':'saved-profile','api_key':'top-secret'}
            try:
                remember(store.config,connection);store.flush();reloaded=load_config(store.config_path)
                self.assertTrue(unsupported(reloaded,connection));self.assertNotIn('top-secret',store.config_path.read_text(encoding='utf-8'))
                self.assertFalse(unsupported(reloaded,dict(connection,model='other')));self.assertFalse(unsupported(reloaded,dict(connection,_capability_scope='new-profile')))
                invalidate_capabilities(reloaded,[connection]);self.assertFalse(unsupported(reloaded,connection))
            finally:store.db.close()






    def test_subagent_status_survives_cancel_and_interrupted_reopen(self):
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
                tab.job=MagicMock();tab.run_id='active';first='a'*32+'-1';second='a'*32+'-2'
                def update(ident,status,text,run='active'):
                    tab.receive({'kind':'subagent','run_id':run,'subagent':{'id':ident,'status':status,'text':text}})
                update(first,'running','first task');update(second,'running','second task');update(first,'completed','first finding')
                self.assertFalse(tab.subagents_toggle.isHidden());self.assertTrue(tab.subagents_view.isHidden());self.assertIn('1 running',tab.subagents_toggle.text());self.assertLess(tab.subagents_view.maximumHeight(),135)
                tab.cancel();self.assertEqual([x['status'] for x in tab.session['coding_subagents']],['completed','cancelled'])
                update(second,'completed','late result');self.assertNotIn('late result',tab.subagents_view.toPlainText())
                saved=store.list_sessions()[0];self.assertEqual([x['status'] for x in saved['coding_subagents']],['completed','cancelled'])
                window.close_tab(window.tabs.indexOf(tab))
                saved['code_state']='running';saved['coding_subagents'][1]['status']='running';saved['coding_subagents'].append({'id':'a'*32+'-3','status':'queued','text':'waiting task'});store.save(saved)
                window.open_session(store.list_sessions()[0]);reopened=window.tabs.currentWidget()
                self.assertEqual(reopened.session['coding_subagents'][1]['status'],'interrupted');self.assertTrue(reopened.subagents_view.isHidden());self.assertIsNone(reopened.job)
                self.assertEqual(reopened.session['coding_subagents'][2]['status'],'interrupted')
            finally:window.close();app.processEvents();store.db.close()

    def test_reject_malformed_or_unexpected_subagent_states(self):
        from agentnik.subagent_status import validate_records
        with self.assertRaises(ValueError):validate_records([{'id':'invalid','status':'running','text':'x'}])
        item={'id':'a'*32+'-1','status':'running','text':'x'}
        with self.assertRaises(ValueError):validate_records([item,item])
        with self.assertRaises(ValueError):validate_records([dict(item,text='x'*1601)])




    def test_individual_cancel_control_keeps_the_other_child_running(self):
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
                job=MagicMock(spec=CodingRun);job.cancel_subagent.return_value=True;tab.job=job;tab.run_id='active';one='a'*32+'-1';two='a'*32+'-2'
                for ident in (one,two):tab.receive({'kind':'subagent','run_id':'active','subagent':{'id':ident,'status':'running','text':'Review '+ident[-1]}})
                tab.subagents_toggle.click();self.assertTrue(tab.stop_subagent_button.isEnabled());tab.stop_subagent_button.click()
                job.cancel_subagent.assert_called_once_with(one);self.assertIs(tab.job,job)
                self.assertEqual([item['status'] for item in tab.session['coding_subagents']],['cancelled','running']);self.assertEqual(tab.subagent_choice.currentData(),two)
                tab.receive({'kind':'subagent','run_id':'active','subagent':{'id':one,'status':'completed','text':'late result'}})
                self.assertNotIn('late result',tab.subagents_view.toPlainText())
                saved=store.list_sessions()[0];self.assertEqual([item['status'] for item in saved['coding_subagents']],['cancelled','running'])
            finally:
                if window.tabs.currentWidget():window.tabs.currentWidget().job=None
                window.close();app.processEvents();store.db.close()

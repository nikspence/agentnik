"""Agentnik coding through existing model protocols, using mock endpoints only."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentnik import core
from agentnik.code_agent import ProjectFiles,CodingRun,TOOLS
from test_routing import Wire,response,function_call,message
from test_compat_tools import chat,msg

C={'url':'https://gateway.example/v1','protocol':'chat','model':'heavy'}

def call(name,args,ident='call-1'):
    return {'id':ident,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}

class ProjectBoundaries(unittest.TestCase):
    def test_delete_and_directory_creation_recheck_approved_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'file.txt';path.write_text('before\n');files=ProjectFiles(directory)
            proposal=files.delete_proposal('file.txt');path.write_text('changed\n')
            with self.assertRaises(ValueError):files.apply_operation(proposal)
            self.assertEqual(path.read_text(),'changed\n')
            files.read('file.txt');files.apply_operation(files.delete_proposal('file.txt'));self.assertFalse(path.exists())
            proposal=files.directory_proposal('new');(root/'new').mkdir()
            with self.assertRaises(ValueError):files.apply_operation(proposal)
            files.apply_operation(files.directory_proposal('other'));self.assertTrue((root/'other').is_dir())
            for name in ('../outside','.git/new','nested/child'):
                with self.assertRaises(ValueError):files.directory_proposal(name)

    def test_project_search_is_bounded_and_respects_file_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'src').mkdir();(root/'src'/'code.py').write_text('needle here\n',encoding='utf-8')
            (root/'.env').write_text('needle secret',encoding='utf-8');(root/'binary').write_bytes(b'needle\x00')
            files=ProjectFiles(directory);result=files.search_project('.','needle')
            self.assertEqual(len(result['matches']),1);self.assertEqual(result['matches'][0]['path'],str(Path('src')/'code.py'))
            self.assertTrue(result['incomplete'])
            with self.assertRaises(ValueError):files.proposal(str(Path('src')/'code.py'),'changed')
            with self.assertRaises(ValueError):files.search_project('..','needle')
            with self.assertRaises(ValueError):files.search_project('.','')

    def test_project_search_stops_at_match_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'many.txt').write_text('\n'.join('needle '+str(n) for n in range(50)),encoding='utf-8')
            result=ProjectFiles(directory).search_project('.','needle')
            self.assertEqual(len(result['matches']),40);self.assertTrue(result['incomplete'])

    def test_search_is_bounded_and_does_not_authorize_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'code.py';path.write_text('\n'.join('needle '+str(n) for n in range(50)),encoding='utf-8')
            files=ProjectFiles(directory);result=files.search('code.py','needle')
            self.assertEqual(result['matches'][0],{'line':1,'text':'needle 0'})
            self.assertEqual(len(result['matches']),40);self.assertTrue(result['truncated'])
            with self.assertRaises(ValueError):files.proposal('code.py','changed')
            for query in ('','x\ny','a'*257):
                with self.assertRaises(ValueError):files.search('code.py',query)
            with self.assertRaises(ValueError):files.search('../outside','needle')

    def test_conflict_does_not_count_as_a_fresh_model_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'code.py';path.write_bytes(b'original\n');files=ProjectFiles(directory)
            files.read('code.py');proposal=files.proposal('code.py','new\n');path.write_bytes(b'user change\n')
            with self.assertRaises(ValueError):files.apply(proposal)
            with self.assertRaises(ValueError):files.proposal('code.py','new\n')
            with self.assertRaises(ValueError):files.proposal('code.py','new\n')
            self.assertEqual(files.read('code.py'),'user change\n')
            files.apply(files.proposal('code.py','reviewed\n'))
            self.assertEqual(path.read_bytes(),b'reviewed\n')

    def test_read_before_edit_conflict_detection_and_approved_write(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'code.py';p.write_text('original\n');files=ProjectFiles(directory)
            with self.assertRaises(ValueError):files.proposal('code.py','new\n')
            files.read('code.py');proposal=files.proposal('code.py','new\n');p.write_text('user changed\n')
            with self.assertRaises(ValueError):files.apply(proposal)
            self.assertEqual(p.read_text(),'user changed\n')
            files.read('code.py');files.apply(files.proposal('code.py','approved\n'))
            self.assertEqual(p.read_text(),'approved\n')
            files.apply(files.proposal('created.py','created\n'));self.assertEqual((Path(directory)/'created.py').read_text(),'created\n')

    def test_sensitive_paths_traversal_binary_and_linked_files_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            files=ProjectFiles(directory)
            for name in ('../escape','.env','.git/config','secret.pem','file:stream','NUL'):
                with self.assertRaises(ValueError):files.path(name)
            p=Path(directory)/'binary';p.write_bytes(b'\x00data')
            with self.assertRaises(ValueError):files.read('binary')

class ModelCoding(unittest.TestCase):
    def test_goal_completion_rejects_unfinished_checklist(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Finish task',goal=True);events=[];bodies=[]
            def plan(status):return call('update_plan',{'explanation':'Work','steps':json.dumps([{'step':'Verify','status':status}])})
            def finish():return call('set_goal_status',{'status':'completed','detail':'Work complete'})
            replies=[Wire(chat(calls=[plan('pending')],finish='tool_calls'),False),Wire(chat(calls=[finish()],finish='tool_calls'),False),Wire(chat(calls=[plan('completed')],finish='tool_calls'),False),Wire(chat(calls=[finish()],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertIn('checklist has unfinished',json.dumps(bodies[2]))
            statuses=[event for event in events if event['kind']=='goal_status'];self.assertEqual(len(statuses),1)
            self.assertIn('No structured test report',statuses[0]['detail'])

    def test_goal_completion_discloses_failed_test_report(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Investigate failure',goal=True);events=[]
            replies=[Wire(chat(calls=[call('run_tests',{'path':'.','command':'python -m unittest','format':'unittest'})],finish='tool_calls'),False),Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Investigation finished'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            result={'exit_code':1,'output':'Ran 1 test in 0.1s\n\nFAILED (failures=1)\n','truncated':False}
            with patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute',return_value=result):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events)
            detail=next(event['detail'] for event in events if event['kind']=='goal_status');self.assertIn('Latest structured test report: failed',detail);self.assertIn('not independent verification',detail)

    def test_goal_completion_flags_test_report_after_later_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Finish',goal=True);run.set_shell_without_approval(True);events=[]
            replies=[Wire(chat(calls=[call('run_tests',{'path':'.','command':'python -m unittest','format':'unittest'})],finish='tool_calls'),False),Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'change'})],finish='tool_calls'),False),Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Done'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            result={'exit_code':0,'output':'Ran 1 test in 0.1s\n\nOK\n','truncated':False}
            with patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute',return_value=result):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);detail=next(e['detail'] for e in events if e['kind']=='goal_status')
            self.assertIn('Latest structured test report: passed',detail);self.assertIn('report may be stale',detail)

    def test_steering_before_approval_does_not_leave_a_pending_proposal(self):
        from agentnik.tools import Runtime
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Task');events=[]
            self.assertTrue(run.steer('Change direction'))
            self.assertFalse(run.review_shell({'operation':'run_shell','command':'echo test'},events.append,Runtime()))
            self.assertFalse(run.review({'operation':'git_stage'},events.append,Runtime(),kind='operation_proposal'))
            self.assertEqual(events,[]);self.assertIsNone(run.pending)

    def test_steering_after_approval_invalidates_without_permanent_denial(self):
        from agentnik.tools import Runtime
        for shell in (False,True):
            with self.subTest(shell=shell),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,stream=False),directory,'Task');events=[];proposal={'operation':'run_shell' if shell else 'git_stage','command':'echo test'}
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':
                        self.assertTrue(run.decide(event['fingerprint'],True));self.assertTrue(run.steer('Wait for correction'))
                review=run.review_shell if shell else lambda proposal,emit,runtime:run.review(proposal,emit,runtime,kind='operation_proposal')
                self.assertFalse(review(proposal,emit,Runtime()));self.assertEqual(events[-1]['kind'],'approval_invalidated')
                self.assertFalse(run.denied);self.assertIsNone(run.pending)

    def test_steering_after_shell_review_prevents_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Task');run.set_shell_without_approval(True);events=[];bodies=[];reviewed=[False]
            replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo test'})],finish='tool_calls'),False),Wire(chat('Adjusted'),False)]
            original_review=run.review_shell;original_path=ProjectFiles.path
            def review(*args):
                result=original_review(*args);reviewed[0]=True;return result
            def path(files,value,*args,**kwargs):
                result=original_path(files,value,*args,**kwargs)
                if reviewed[0]:reviewed[0]=False;self.assertTrue(run.steer('Do not run the command'))
                return result
            def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(run,'review_shell',side_effect=review),patch.object(ProjectFiles,'path',path),patch.object(core,'open_request',side_effect=send),patch('agentnik.shell.execute') as execute:
                run.run(events.append);execute.assert_not_called()
            self.assertEqual(events[-1]['status'],'completed',events);self.assertIn('Do not run the command',json.dumps(bodies[-1]))

    def test_steering_failure_reports_delivery_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Task');events=[];count=[0]
            def send(connection,url,body,timeout):
                count[0]+=1
                if count[0]==1:
                    self.assertTrue(run.steer('Correction'));return Wire(chat('First answer'),False)
                raise core.EndpointError(503,'private detail')
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'failed');self.assertEqual([e['text'] for e in events if e['kind']=='steering_uncertain'],['Correction'])
            self.assertFalse(any(e['kind']=='steering_delivered' for e in events));self.assertNotIn('private detail',json.dumps(events))

    def test_stop_preserves_confirmed_steering_until_acknowledged(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Task');events=[];delivered=threading.Event();release=threading.Event();count=[0]
            def send(connection,url,body,timeout):
                count[0]+=1
                if count[0]==1:self.assertTrue(run.steer('Correction'))
                return Wire(chat('Response'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='steering_delivered':delivered.set();release.wait(5)
            with patch.object(core,'open_request',side_effect=send):
                worker=threading.Thread(target=run.run,args=(emit,));worker.start()
                try:
                    self.assertTrue(delivered.wait(5));outcome=run.stop()
                    self.assertEqual(outcome['delivered'],['Correction']);self.assertEqual(outcome['uncertain'],[]);self.assertEqual(outcome['undelivered'],[])
                finally:release.set();worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_steering_limit_before_request_reports_not_delivered(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits['context_bytes']=4096
            run=CodingRun(dict(C,stream=False),directory,'Task',limits=limits);events=[];message='x'*8000
            def send(connection,url,body,timeout):
                self.assertTrue(run.steer(message));return Wire(chat('First answer'),False)
            with patch.object(core,'open_request',side_effect=send) as transport:run.run(events.append)
            self.assertEqual(transport.call_count,1);self.assertTrue(events[-1]['limited'])
            self.assertEqual([e['text'] for e in events if e['kind']=='steering_undelivered'],[message]);self.assertFalse(any(e['kind']=='steering_delivered' for e in events))

    def test_removed_light_delegation_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Analyze');bodies=[];events=[]
            replies=[Wire(chat(calls=[call('delegate_light',{'task':'Analyze'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(connection,url,body,timeout):bodies.append((connection['model'],json.loads(json.dumps(body))));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual([model for model,_ in bodies],[C['model'],C['model']]);self.assertEqual(events[-1]['status'],'completed')
            self.assertNotIn('delegate_light',json.dumps(bodies[0][1]['tools']));self.assertIn('Unknown or unavailable tool',json.dumps(bodies[-1][1]))

    def test_removed_parallel_delegation_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Analyze');bodies=[];events=[]
            replies=[Wire(chat(calls=[call('delegate_parallel',{'tasks':'["one","two"]'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(connection,url,body,timeout):bodies.append((connection['model'],json.loads(json.dumps(body))));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual([model for model,_ in bodies],[C['model'],C['model']]);self.assertEqual(events[-1]['status'],'completed')
            self.assertNotIn('delegate_parallel',json.dumps(bodies[0][1]['tools']));self.assertIn('Unknown or unavailable tool',json.dumps(bodies[-1][1]))

    def test_model_timeout_does_not_change_web_timeout(self):
        from agentnik.tools import Source
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits['model_seconds']=240;timeouts=[];events=[]
            replies=[Wire(chat(calls=[call('web_fetch',{'url':'https://example.com/docs'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(connection,url,body,timeout):timeouts.append(timeout);return replies.pop(0)
            def fetch(url,runtime):
                self.assertEqual(runtime.limits.request_seconds,45);return [Source('','Docs',url,'Documentation','now')]
            with patch.object(core,'open_request',side_effect=send),patch('agentnik.code_agent.PublicWeb') as reader:
                reader.return_value.fetch.side_effect=fetch
                CodingRun(dict(C,stream=False),directory,'Research',limits=limits,web_enabled=True,search_provider='none').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertEqual(len(timeouts),2);self.assertTrue(all(239<timeout<=240 for timeout in timeouts))

    def test_removed_review_tools_are_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Review');bodies=[];events=[]
            replies=[Wire(chat(calls=[call('review_document',{'path':'spec.md','model':'light'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(len(bodies),2);self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('Unknown or unavailable tool',json.dumps(bodies[-1]));self.assertFalse(any(e['kind']=='operation_proposal' for e in events))
            self.assertFalse(any(tool.get('function',{}).get('name','').startswith('review_document') for tool in bodies[0]['tools']))

    def test_goal_continues_until_explicit_completion_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Complete the task',goal=True);events=[];bodies=[]
            replies=[Wire(chat('First step done'),False),Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Checked the requested result'})],finish='tool_calls'),False),Wire(chat('Completed and checked'),False)]
            def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(len(bodies),3);self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('Continue the current goal',json.dumps(bodies[1]))
            self.assertEqual([e['status'] for e in events if e['kind']=='goal_status'],['completed'])

    def test_goal_limit_is_not_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            from agentnik.code_limits import coding_limits
            limits=coding_limits();limits['rounds']=1
            run=CodingRun(dict(C,stream=False),directory,'Unfinished goal',limits=limits,goal=True);events=[]
            replies=[Wire(chat(calls=[call('get_plan',{})],finish='tool_calls'),False),Wire(chat(calls=[call('get_plan',{})],finish='tool_calls'),False)]
            with patch.object(core,'open_request',side_effect=replies):run.run(events.append)
            self.assertEqual(events[-1]['status'],'failed');self.assertTrue(events[-1]['limited']);self.assertEqual(run.goal_status,'active')

    def test_goal_steps_receive_fresh_request_and_round_budgets(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits.update(requests=2,rounds=1,calls=1)
            run=CodingRun(dict(C,stream=False),directory,'Complete task',limits=limits,goal=True);events=[]
            replies=[]
            for index in range(2):replies.extend([Wire(chat(calls=[call('get_plan',{},str(index))],finish='tool_calls'),False),Wire(chat('Step complete'),False)])
            replies.extend([Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Reviewed'})],finish='tool_calls'),False),Wire(chat('Done'),False)])
            with patch.object(core,'open_request',side_effect=replies) as send:run.run(events.append)
            self.assertEqual(send.call_count,6);self.assertEqual(events[-1]['status'],'completed',events)
            self.assertEqual(sum(e['kind']=='output' and 'continuing to the next step' in e.get('text','') for e in events),2)

    def test_goal_step_limit_stops_before_next_step_and_resume_is_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Finish',goal=True,goal_budget={'steps':2,'seconds':0});events=[]
            with patch.object(core,'open_request',side_effect=[Wire(chat('Step one'),False),Wire(chat('Step two'),False)]) as send:run.run(events.append)
            self.assertEqual(send.call_count,2);self.assertTrue(events[-1]['limited']);self.assertIn('goal step limit',events[-1]['text']);self.assertEqual(events[-1]['goal_progress']['steps'],2)
            resumed=CodingRun(dict(C,stream=False),directory,'Continue',goal=True,goal_budget={'steps':2,'seconds':0},resume_context={'task':'Finish','evidence':'Two steps completed'});events=[]
            replies=[Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Finished'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            with patch.object(core,'open_request',side_effect=replies) as send:resumed.run(events.append)
            self.assertEqual(send.call_count,2);self.assertEqual(events[-1]['status'],'completed');self.assertEqual(events[-1]['goal_progress']['steps'],1)

    def test_goal_steering_at_step_boundary_uses_fresh_limits(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits.update(requests=2,rounds=1,calls=1)
            run=CodingRun(dict(C,stream=False),directory,'Finish',limits=limits,goal=True);events=[];bodies=[]
            replies=[Wire(chat(calls=[call('get_plan',{})],finish='tool_calls'),False),Wire(chat('Step done'),False),Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Addressed correction'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(connection,url,body,timeout):
                bodies.append(json.loads(json.dumps(body)))
                if len(bodies)==2:self.assertTrue(run.steer('Apply this correction'))
                return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(len(bodies),4)
            self.assertIn('Apply this correction',json.dumps(bodies[2]));self.assertEqual([e['text'] for e in events if e['kind']=='steering_delivered'],['Apply this correction'])

    def test_steering_reopens_terminal_goal_before_final_response(self):
        for initial_status in ('completed','blocked'):
            with self.subTest(status=initial_status),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,stream=False),directory,'Finish',goal=True);events=[];bodies=[]
                replies=[Wire(chat(calls=[call('set_goal_status',{'status':initial_status,'detail':'Initial assessment'})],finish='tool_calls'),False),Wire(chat('Initial response'),False),Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Correction addressed'})],finish='tool_calls'),False),Wire(chat('Revised response'),False)]
                def send(connection,url,body,timeout):
                    bodies.append(json.loads(json.dumps(body)))
                    if len(bodies)==2:self.assertTrue(run.steer('Please address this correction'))
                    return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):run.run(events.append)
                self.assertEqual(len(bodies),4);self.assertIn('Please address this correction',json.dumps(bodies[2]))
                self.assertEqual([e['status'] for e in events if e['kind']=='goal_status'],[initial_status,'completed'])
                self.assertEqual(events[-1]['status'],'completed');self.assertEqual(events[-1]['text'],'Revised response')

    def test_goal_step_reset_keeps_retained_request_bounded(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits['context_bytes']=4096
            run=CodingRun(dict(C,stream=False),directory,'p'*2500,limits=limits,goal=True);events=[]
            def send(connection,url,body,timeout):
                self.assertTrue(run.steer('Correction'));return Wire(chat('a'*2500),False)
            with patch.object(core,'open_request',side_effect=send) as transport:run.run(events.append)
            self.assertEqual(transport.call_count,1);self.assertTrue(events[-1]['limited']);self.assertIn('context bytes limit',events[-1]['text'])
            self.assertEqual([e['text'] for e in events if e['kind']=='steering_undelivered'],['Correction']);self.assertFalse(any(e['kind']=='steering_delivered' for e in events))

    def test_goal_small_context_limit_does_not_charge_fixed_tool_definitions_on_reset(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits['context_bytes']=4096;events=[]
            run=CodingRun(dict(C,stream=False),directory,'Finish',limits=limits,goal=True)
            replies=[Wire(chat('Step done'),False),Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Finished'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            with patch.object(core,'open_request',side_effect=replies) as transport:run.run(events.append)
            self.assertEqual(transport.call_count,3);self.assertEqual(events[-1]['status'],'completed',events)

    def test_goal_small_context_reset_is_consistent_across_protocols(self):
        from agentnik.code_limits import coding_limits
        from test_research import Response,answer
        for protocol,url in [('chat','https://gateway.example/v1'),('messages','https://gateway.example/v1'),('responses','https://gateway.example/v1'),('chat','http://localhost:11434/v1')]:
            with self.subTest(protocol=protocol,url=url),tempfile.TemporaryDirectory() as directory:
                limits=coding_limits();limits['context_bytes']=4096;events=[]
                run=CodingRun(dict(C,protocol=protocol,url=url,stream=False),directory,'Finish',limits=limits,goal=True,goal_budget={'steps':2,'seconds':0})
                if protocol=='messages':replies=[Wire(msg([{'type':'text','text':'Step'}]),False) for _ in range(2)]
                elif protocol=='responses':replies=[Wire(response([message('Step')]),False) for _ in range(2)]
                elif 'localhost' in url:replies=[Response([answer('Step')]) for _ in range(2)]
                else:replies=[Wire(chat('Step'),False) for _ in range(2)]
                with patch.object(core,'open_request',side_effect=replies) as transport:run.run(events.append)
                self.assertEqual(transport.call_count,2);self.assertTrue(events[-1]['limited']);self.assertIn('goal step limit',events[-1]['text'])

    def test_goal_step_limit_reports_boundary_steering_undelivered(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Finish',goal=True,goal_budget={'steps':1,'seconds':0});events=[]
            def send(connection,url,body,timeout):self.assertTrue(run.steer('Correction'));return Wire(chat('Step done'),False)
            with patch.object(core,'open_request',side_effect=send) as transport:run.run(events.append)
            self.assertEqual(transport.call_count,1);self.assertTrue(events[-1]['limited']);self.assertEqual([e['text'] for e in events if e['kind']=='steering_undelivered'],['Correction'])

    def test_goal_time_limit_interrupts_inflight_model_request(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Finish',goal=True,goal_budget={'steps':0,'seconds':1});events=[];release=threading.Event()
            def delayed(*args,**kwargs):release.wait(3);return Wire(chat('Late answer'),False)
            try:
                with patch.object(core,'open_request',side_effect=delayed):run.run(events.append)
                self.assertTrue(events[-1]['limited']);self.assertIn('goal time limit',events[-1]['text']);self.assertGreaterEqual(events[-1]['goal_progress']['seconds'],1)
            finally:release.set()

    def test_shell_approval_displays_goal_time_remaining(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Run command',goal=True,goal_budget={'steps':0,'seconds':5});events=[]
            replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo test'})],finish='tool_calls'),False),Wire(chat(calls=[call('set_goal_status',{'status':'blocked','detail':'Command declined'})],finish='tool_calls'),False),Wire(chat('Blocked'),False)]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],False)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            proposal=next(e['proposal'] for e in events if e['kind']=='operation_proposal');self.assertLessEqual(proposal['max_seconds'],5);self.assertEqual(events[-1]['status'],'blocked')

    def test_goal_steering_and_tool_results_across_protocols(self):
        from test_research import Response,answer,call as native_call
        for protocol,url in [('responses','https://gateway.example/v1'),('messages','https://gateway.example/v1'),('chat','http://localhost:11434/v1')]:
            with self.subTest(protocol=protocol),tempfile.TemporaryDirectory() as directory:
                Path(directory,'file.txt').write_text('content',encoding='utf-8')
                args={'status':'completed','detail':'Reviewed result'}
                if protocol=='responses':
                    first=dict(function_call('read'),name='read_file',arguments=json.dumps({'path':'file.txt'}));done=dict(function_call('goal'),name='set_goal_status',arguments=json.dumps(args))
                    replies=[Wire(response([first]),False),Wire(response([done]),False),Wire(response([message('Done')]),False)]
                elif protocol=='messages':
                    replies=[Wire(msg([{'type':'tool_use','id':'read','name':'read_file','input':{'path':'file.txt'}}],'tool_use'),False),Wire(msg([{'type':'tool_use','id':'goal','name':'set_goal_status','input':args}],'tool_use'),False),Wire(msg([{'type':'text','text':'Done'}]),False)]
                else:
                    replies=[Response([answer('',[native_call('read_file',{'path':'file.txt'})])]),Response([answer('',[native_call('set_goal_status',args)])]),Response([answer('Done')])]
                run=CodingRun(dict(C,protocol=protocol,url=url,stream=False),directory,'Complete task',goal=True);bodies=[];events=[]
                def send(connection,endpoint,body,timeout):
                    bodies.append(json.loads(json.dumps(body)))
                    if len(bodies)==1:self.assertTrue(run.steer('Use the revised scope'))
                    return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):run.run(events.append)
                self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(len(bodies),3)
                second=bodies[1]['input' if protocol=='responses' else 'messages'];serialized=json.dumps(second)
                self.assertIn('Use the revised scope',serialized);self.assertIn('reconsider this tool call',serialized)
                if protocol=='responses':self.assertTrue(any(x.get('type')=='function_call_output' and x.get('call_id')=='read' for x in second))
                elif protocol=='messages':self.assertTrue(any(x.get('role')=='user' and isinstance(x.get('content'),list) and any(block.get('tool_use_id')=='read' for block in x['content'] if isinstance(block,dict)) for x in second))
                else:self.assertTrue(any(x.get('role')=='tool' and x.get('tool_call_id')=='call-0' for x in second))

    def test_streaming_steering_defers_fragmented_tool_calls(self):
        for goal in (False,True):
            with self.subTest(goal=goal),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,stream=True),directory,'Original task',goal=goal);events=[];bodies=[]
                class SteeringWire(Wire):
                    def readline(self,size=-1):
                        line=super().readline(size)
                        if line.startswith(b'data:') and not getattr(self,'steered',False):
                            self.steered=True;self_outer.assertTrue(run.steer('Do not write the file'))
                        return line
                self_outer=self
                first=[{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'write','type':'function','function':{'name':'write_file','arguments':'{"path":"new.txt",'}}]}}]},
                       {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"content":"wrong"}'}}]},'finish_reason':'tool_calls'}]}]
                final=[{'choices':[{'delta':{'content':'Adjusted'},'finish_reason':'stop'}]}]
                replies=[SteeringWire(first)]
                if goal:
                    done={'index':0,'id':'goal','type':'function','function':{'name':'set_goal_status','arguments':json.dumps({'status':'completed','detail':'Adjusted as requested'})}}
                    replies.append(Wire([{'choices':[{'delta':{'tool_calls':[done]},'finish_reason':'tool_calls'}]}]))
                replies.append(Wire(final))
                def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):run.run(events.append)
                self.assertEqual(events[-1]['status'],'completed',events);self.assertFalse(Path(directory,'new.txt').exists())
                messages=bodies[1]['messages'];self.assertIn('Do not write the file',json.dumps(messages));self.assertIn('reconsider this tool call',json.dumps(messages))
                self.assertTrue(any(m.get('role')=='tool' and m.get('tool_call_id')=='write' for m in messages))
                self.assertEqual([e['text'] for e in events if e['kind']=='steering_delivered'],['Do not write the file'])

    def test_messages_streaming_steering_defers_tool_call(self):
        for goal in (False,True):
            with self.subTest(goal=goal),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,protocol='messages',stream=True),directory,'Original task',goal=goal);events=[];bodies=[]
                class SteeringWire(Wire):
                    def readline(self,size=-1):
                        line=super().readline(size)
                        if line.startswith(b'data:') and not getattr(self,'steered',False):
                            self.steered=True;self_outer.assertTrue(run.steer('Do not write the file'))
                        return line
                self_outer=self
                def tool_events(name,ident,args):
                    encoded=json.dumps(args);middle=len(encoded)//2
                    return [{'type':'message_start','message':{}},{'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':ident,'name':name,'input':{}}},
                            *[{'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':part}} for part in (encoded[:middle],encoded[middle:])],
                            {'type':'content_block_stop','index':0},{'type':'message_delta','delta':{'stop_reason':'tool_use'}},{'type':'message_stop'}]
                final=[{'type':'message_start','message':{}},{'type':'content_block_start','index':0,'content_block':{'type':'text','text':'Adjusted'}},{'type':'content_block_stop','index':0},{'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}]
                replies=[SteeringWire(tool_events('write_file','write',{'path':'new.txt','content':'wrong'}))]
                if goal:replies.append(Wire(tool_events('set_goal_status','goal',{'status':'completed','detail':'Adjusted as requested'})))
                replies.append(Wire(final))
                def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):run.run(events.append)
                self.assertEqual(events[-1]['status'],'completed',events);self.assertFalse(Path(directory,'new.txt').exists())
                messages=bodies[1]['messages'];self.assertIn('Do not write the file',json.dumps(messages));self.assertIn('reconsider this tool call',json.dumps(messages))
                self.assertTrue(any(m.get('role')=='user' and isinstance(m.get('content'),list) and any(b.get('tool_use_id')=='write' for b in m['content'] if isinstance(b,dict)) for m in messages))
                self.assertEqual([e['text'] for e in events if e['kind']=='steering_delivered'],['Do not write the file'])

    def test_responses_streaming_steering_defers_tool_call(self):
        for goal in (False,True):
            with self.subTest(goal=goal),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,protocol='responses',stream=True),directory,'Original task',goal=goal);events=[];bodies=[]
                class SteeringWire(Wire):
                    def readline(self,size=-1):
                        line=super().readline(size)
                        if line.startswith(b'data:') and not getattr(self,'steered',False):
                            self.steered=True;self_outer.assertTrue(run.steer('Do not write the file'))
                        return line
                self_outer=self
                def tool_events(name,ident,args):
                    arguments=json.dumps(args);middle=len(arguments)//2;item=dict(function_call(ident,arguments),name=name)
                    return [{'type':'response.output_item.added','output_index':0,'item':dict(item,arguments='')},
                            *[{'type':'response.function_call_arguments.delta','output_index':0,'delta':part} for part in (arguments[:middle],arguments[middle:])],
                            {'type':'response.output_item.done','output_index':0,'item':item},{'type':'response.completed','response':response([item])}]
                replies=[SteeringWire(tool_events('write_file','write',{'path':'new.txt','content':'wrong'}))]
                if goal:replies.append(Wire(tool_events('set_goal_status','goal',{'status':'completed','detail':'Adjusted as requested'})))
                replies.append(Wire([{'type':'response.completed','response':response([message('Adjusted')])}]))
                def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):run.run(events.append)
                self.assertEqual(events[-1]['status'],'completed',events);self.assertFalse(Path(directory,'new.txt').exists())
                items=bodies[1]['input'];self.assertIn('Do not write the file',json.dumps(items));self.assertIn('reconsider this tool call',json.dumps(items))
                self.assertTrue(any(item.get('type')=='function_call_output' and item.get('call_id')=='write' for item in items))
                self.assertEqual([e['text'] for e in events if e['kind']=='steering_delivered'],['Do not write the file'])

    def test_ollama_streaming_steering_defers_tool_call(self):
        from test_research import Response,answer
        for goal in (False,True):
            with self.subTest(goal=goal),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,url='http://localhost:11434/v1',stream=True),directory,'Original task',goal=goal);events=[];bodies=[]
                class SteeringResponse(Response):
                    def readline(self,size=-1):
                        line=super().readline(size)
                        if line and not getattr(self,'steered',False):
                            self.steered=True;self_outer.assertTrue(run.steer('Do not write the file'))
                        return line
                self_outer=self
                def tool_events(name,ident,args):
                    encoded=json.dumps(args);middle=len(encoded)//2
                    return [{'message':{'role':'assistant','tool_calls':[{'id':ident,'function':{'index':0,'name':name,'arguments':encoded[:middle]}}]},'done':False},
                            {'message':{'role':'assistant','tool_calls':[{'id':ident,'function':{'index':0,'arguments':encoded[middle:]}}]},'done':True}]
                replies=[SteeringResponse(tool_events('write_file','write',{'path':'new.txt','content':'wrong'}))]
                if goal:replies.append(Response(tool_events('set_goal_status','goal',{'status':'completed','detail':'Adjusted as requested'})))
                replies.append(Response([answer('Adjusted')]))
                def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):run.run(events.append)
                self.assertEqual(events[-1]['status'],'completed',events);self.assertFalse(Path(directory,'new.txt').exists())
                messages=bodies[1]['messages'];self.assertIn('Do not write the file',json.dumps(messages));self.assertIn('reconsider this tool call',json.dumps(messages))
                self.assertTrue(any(m.get('role')=='tool' and m.get('tool_call_id')=='write' for m in messages))
                self.assertEqual([e['text'] for e in events if e['kind']=='steering_delivered'],['Do not write the file'])

    def test_steering_is_delivered_after_inflight_model_response(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Original task');events=[];bodies=[]
            def send(connection,url,body,timeout):
                bodies.append(json.loads(json.dumps(body)))
                if len(bodies)==1:
                    self.assertTrue(run.steer('First correction'));self.assertTrue(run.steer('Second correction'))
                    return Wire(chat('Initial answer'),False)
                return Wire(chat('Revised answer'),False)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertEqual(len(bodies),2)
            messages=bodies[-1]['messages'];texts=[m['content'] for m in messages if m.get('role')=='user']
            self.assertEqual(texts[-2:],['First correction','Second correction'])
            self.assertEqual([e['text'] for e in events if e['kind']=='steering_delivered'],['First correction','Second correction'])
            self.assertFalse(run.steer('too late'))

    def test_steering_invalidates_pending_shell_and_defers_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Original task');events=[];bodies=[]
            replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo one'}),call('write_file',{'path':'new.txt','content':'bad'},'second')],finish='tool_calls'),False),Wire(chat('Adjusted'),False)]
            def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':self.assertTrue(run.steer('Do not make those changes'))
            with patch.object(core,'open_request',side_effect=send),patch('agentnik.shell.execute') as execute:run.run(emit);execute.assert_not_called()
            self.assertFalse(Path(directory,'new.txt').exists());self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('Do not make those changes',json.dumps(bodies[-1]));self.assertIn('reconsider this tool call',json.dumps(bodies[-1]))
    def test_compare_git_branches_is_read_only_and_model_can_correct_bad_ref(self):
        from dulwich import porcelain
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=porcelain.init(directory)
            try:
                config=repo.get_config();config.set((b'user',),b'name',b'Test');config.set((b'user',),b'email',b'test@example.invalid');config.write_to_path()
                (root/'file').write_text('content');porcelain.add(repo,['file']);porcelain.commit(repo,message=b'initial',no_verify=True,sign=False)
                branch=repo.refs.follow(b'HEAD')[0][-1].decode();repo.refs[b'refs/remotes/origin/main']=repo.head()
                calls=[call('git_remote_branches',{}),call('git_compare_refs',{'left':'bad','right':'refs/remotes/origin/main'},'bad')]
                good={'left':branch,'right':'refs/remotes/origin/main'}
                replies=[Wire(chat(calls=calls,finish='tool_calls'),False),Wire(chat(calls=[call('git_compare_refs',good,'good'),call('git_changed_files',good,'files'),call('git_diff_refs',{**good,'path':'file'},'diff')],finish='tool_calls'),False),Wire(chat('Done'),False)]
                bodies=[];events=[]
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),directory,'Compare branches').run(events.append)
                self.assertIn('refs/remotes/origin/main',json.dumps(bodies[1]));self.assertIn('Use exact refs',json.dumps(bodies[1]));self.assertIn('"relationship": "equal"',json.dumps(bodies[2]).replace('\\"','"'))
                self.assertIn('"changes": []',json.dumps(bodies[2]).replace('\\"','"'));self.assertIn('"path": "file"',json.dumps(bodies[2]).replace('\\"','"'))
                self.assertFalse(any(event['kind']=='operation_proposal' for event in events));self.assertEqual(events[-1]['status'],'completed')
            finally:repo.close()

    def test_git_credentials_are_transient_and_do_not_reach_model_or_events(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Fetch');events=[];bodies=[]
            destination={'operation':'git_fetch_connect','cwd':directory,'remote':'origin','branch':'main','url':'https://example.invalid/repo','target':'refs/remotes/origin/main','previous':''}
            git=Mock();git.fetch_destination.return_value=destination;git.fetch_preview.return_value={**destination,'operation':'git_fetch','commit':'a'*40};git.fetch_apply.return_value={'fetched':True}
            replies=[Wire(chat(calls=[call('git_fetch',{'remote':'origin','branch':'main'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':
                    if event['proposal']['operation']=='git_fetch_connect':run.decide(event['fingerprint'],True,git_credentials=('user','secret-token'))
                    else:run.decide(event['fingerprint'],True)
            with patch('agentnik.git_service.GitService',return_value=git),patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(git.fetch_preview.call_args.args[-1],('user','secret-token'));self.assertEqual(git.fetch_apply.call_args.args[-1],('user','secret-token'))
            self.assertNotIn('secret-token',json.dumps(events)+json.dumps(bodies));self.assertIsNone(run._git_credentials)

    def test_git_push_approval_and_uncertain_outcome_stops_run(self):
        from unittest.mock import Mock
        for deny in ('git_push_connect','git_push','none'):
            with self.subTest(deny=deny),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,stream=False),directory,'Push');events=[]
                destination={'operation':'git_push_connect','cwd':directory,'remote':'origin','branch':'main','local_branch':'main','url':'https://example.invalid/repo','target':'refs/heads/main','commit':'a'*40}
                git=Mock();git.push_destination.return_value=destination;git.push_preview.return_value={**destination,'operation':'git_push','previous':'b'*40};git.push_apply.side_effect=OSError('sensitive remote error')
                replies=[Wire(chat(calls=[call('git_push',{'remote':'origin','branch':'main','local_branch':'main'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':run.decide(event['fingerprint'],event['proposal']['operation']!=deny)
                with patch('agentnik.git_service.GitService',return_value=git),patch.object(core,'open_request',side_effect=replies):run.run(emit)
                if deny=='git_push_connect':git.push_preview.assert_not_called()
                if deny!='none':git.push_apply.assert_not_called();self.assertEqual(events[-1]['status'],'completed')
                else:git.push_apply.assert_called_once();self.assertEqual(events[-1]['status'],'failed');self.assertIn('outcome is uncertain',events[-1]['text']);self.assertNotIn('sensitive remote error',str(events))

    def test_git_fetch_requires_both_approvals_and_returns_result(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            events=[];bodies=[];run=CodingRun(dict(C,stream=False),directory,'Fetch branch')
            destination={'operation':'git_fetch_connect','cwd':directory,'remote':'origin','branch':'main','url':'https://example.invalid/repo','target':'refs/remotes/origin/main','previous':''}
            proposal={**destination,'operation':'git_fetch','commit':'a'*40}
            git=Mock();git.fetch_destination.return_value=destination;git.fetch_preview.return_value=proposal;git.fetch_apply.return_value={'fetched':True,'commit':'a'*40}
            replies=[Wire(chat(calls=[call('git_fetch',{'remote':'origin','branch':'main'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':
                    if event['proposal']['operation']=='git_fetch_connect':git.fetch_preview.assert_not_called()
                    else:git.fetch_apply.assert_not_called()
                    run.decide(event['fingerprint'],True)
            with patch('agentnik.git_service.GitService',return_value=git),patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual([e['proposal']['operation'] for e in events if e['kind']=='operation_proposal'],['git_fetch_connect','git_fetch'])
            git.fetch_apply.assert_called_once();self.assertIn('fetched',json.dumps(bodies[1]));self.assertEqual(events[-1]['status'],'completed')

    def test_git_fetch_denial_stops_before_network_or_download(self):
        from unittest.mock import Mock
        for deny in ('git_fetch_connect','git_fetch'):
            with self.subTest(deny=deny),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,stream=False),directory,'Fetch');events=[]
                destination={'operation':'git_fetch_connect','cwd':directory,'remote':'origin','branch':'main','url':'https://example.invalid/repo','target':'refs/remotes/origin/main','previous':''}
                git=Mock();git.fetch_destination.return_value=destination;git.fetch_preview.return_value={**destination,'operation':'git_fetch','commit':'a'*40}
                replies=[Wire(chat(calls=[call('git_fetch',{'remote':'origin','branch':'main'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':run.decide(event['fingerprint'],event['proposal']['operation']!=deny)
                with patch('agentnik.git_service.GitService',return_value=git),patch.object(core,'open_request',side_effect=replies):run.run(emit)
                git.fetch_apply.assert_not_called()
                if deny=='git_fetch_connect':git.fetch_preview.assert_not_called()
                self.assertEqual(events[-1]['status'],'completed')

    def test_tool_argument_guidance_survives_protocol_adapters(self):
        from agentnik import responses_tools,compat_tools
        selected=[next(t for t in TOOLS if t.name==name) for name in ('apply_patch','update_plan','run_shell')]
        for definitions in ([t.wire()['function'] for t in selected],responses_tools.wire_tools(selected),compat_tools.wire_tools(selected,'messages')):
            by_name={item['name']:item for item in definitions}
            schema=by_name['update_plan'].get('parameters',by_name['update_plan'].get('input_schema'))
            self.assertIn('JSON array encoded as a string',schema['properties']['steps']['description'])
            self.assertIn('not a unified diff',by_name['apply_patch']['description'])
            self.assertIn('user approval',by_name['run_shell']['description'])
            self.assertEqual(set(schema['required']),{'explanation','steps'})

    def test_git_remotes_tool_returns_redacted_local_configuration(self):
        from dulwich import porcelain
        with tempfile.TemporaryDirectory() as directory:
            repo=porcelain.init(directory)
            try:
                config=repo.get_config();config.set((b'remote',b'origin'),b'url',b'https://user:secret@example.invalid/private');config.write_to_path()
                bodies=[];replies=[Wire(chat(calls=[call('git_remotes',{})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                run=CodingRun(dict(C,stream=False),directory,'Inspect remotes');events=[]
                with patch.object(core,'open_request',side_effect=send):run.run(events.append)
                output=next(item['content'] for item in bodies[1]['messages'] if item['role']=='tool');self.assertIn('origin',output);self.assertIn('https',output);self.assertNotIn('secret',output);self.assertNotIn('example.invalid',output)
                self.assertEqual(events[-1]['status'],'completed')
            finally:repo.close()

    def test_initial_request_includes_coding_attachments(self):
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/'example.png';image.write_bytes(b'image')
            bodies=[];events=[]
            def send(c,url,body,timeout):
                bodies.append(body);return Wire(chat('Done'),False)
            run=CodingRun(dict(C,stream=False),directory,'Review',images=[str(image)],documents=[{'name':'notes.txt','text':'Document evidence'}])
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            message=next(item for item in bodies[0]['messages'] if item['role']=='user')
            self.assertIn('Document evidence',json.dumps(message));self.assertIn('image_url',json.dumps(message))
            self.assertEqual(events[-1]['status'],'completed')

    def setUp(self):
        from agentnik import search_cache
        search_cache._entries.clear()

    def tearDown(self):
        from agentnik import search_cache
        search_cache._entries.clear()

    def test_mcp_search_cache_reuses_only_success_and_verifies_each_hit(self):
        from unittest.mock import Mock
        detail={'name':'web_search','description':'Search','description_clipped':False,'schema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query'],'additionalProperties':False},'schema_status':'available','annotations':{'readOnlyHint':True}}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Search','command':'search','args':[],'enabled':True};bridge.cache_scope='account-one'
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'text','text':'result'}]}},{'verified':True}]
            args={'tool':'web_search','arguments':'{"query":"same"}'}
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',args),call('mcp_call',args,'second')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Search',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual([x.args[0] for x in bridge.request.call_args_list],['discover','call','verify'])
            self.assertEqual(len([x for x in events if x['kind']=='operation_proposal']),0)
            self.assertTrue(any('reused recent cached' in x.get('text','') for x in events))
            self.assertEqual(events[-1]['status'],'completed')

    def test_mcp_user_directed_content_does_not_enter_model_context_or_cache_hits(self):
        from unittest.mock import Mock
        detail={'name':'search','description':'Search','description_clipped':False,'schema':{'type':'object'},'schema_status':'available','annotations':{'readOnlyHint':True}}
        result={'content':[{'type':'text','text':'user-only-fixture','annotations':{'audience':['user']}},{'type':'text','text':'model-fixture','annotations':{'audience':['assistant']}}]}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Search','command':'search','args':[],'enabled':True};bridge.cache_scope='account-audience'
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':result},{'verified':True}]
            args={'tool':'search','arguments':'{"query":"same"}'};bodies=[];events=[]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',args),call('mcp_call',args,'second')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Search',mcp_bridge=bridge)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual([item.args[0] for item in bridge.request.call_args_list],['discover','call','verify'])
            self.assertNotIn('user-only-fixture',json.dumps(bodies));self.assertIn('model-fixture',json.dumps(bodies))
            self.assertEqual(sum('user-only-fixture' in event.get('text','') for event in events),2);self.assertEqual(events[-1]['status'],'completed')

    def test_invalid_mcp_audience_does_not_enter_model_context_or_cache(self):
        from unittest.mock import Mock
        detail={'name':'search','description':'Search','description_clipped':False,'schema':{'type':'object'},'schema_status':'available','annotations':{'readOnlyHint':True}}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Search','command':'search','args':[],'enabled':True};bridge.cache_scope='account-invalid-audience'
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'text','text':'do-not-forward','annotations':{'audience':'user'}}]}},{'call_result':{'content':[{'type':'text','text':'valid'}]}}]
            args={'tool':'search','arguments':'{"query":"same"}'};bodies=[]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',args)],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',args,'second')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Search',mcp_bridge=bridge)
            def emit(event):
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual([item.args[0] for item in bridge.request.call_args_list],['discover','call','call'])
            self.assertNotIn('do-not-forward',json.dumps(bodies));self.assertIn('invalid audience metadata',json.dumps(bodies))

    def test_mcp_user_directed_activity_is_bounded_and_redacted(self):
        from unittest.mock import Mock
        detail={'name':'query','description':'Query','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Local','command':'server','args':[],'enabled':True}
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'text','text':'private-key-fixture '+('x'*3000),'annotations':{'audience':['user']}}]}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'query','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False,api_key='private-key-fixture'),directory,'Query',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            text=next(e['text'] for e in events if e.get('kind')=='output' and 'user-directed content' in e.get('text',''))
            self.assertIn('[redacted]',text);self.assertIn('[Content truncated]',text);self.assertNotIn('private-key-fixture',text);self.assertLess(len(text),2000)

    def test_mcp_search_errors_are_not_cached(self):
        from unittest.mock import Mock
        detail={'name':'search','description':'Search','description_clipped':False,'schema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']},'schema_status':'available','annotations':{'readOnlyHint':True}}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Search','command':'search','args':[],'enabled':True};bridge.cache_scope='account-one'
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'isError':True,'content':[]}},{'call_result':{'content':[{'type':'text','text':'result'}]}}]
            args={'tool':'search','arguments':'{"query":"same"}'}
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',args),call('mcp_call',args,'second')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Search',mcp_bridge=bridge)
            def emit(event):
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual([x.args[0] for x in bridge.request.call_args_list],['discover','call','call'])

    def test_mcp_structured_results_are_validated_before_caching(self):
        from unittest.mock import Mock
        detail={'name':'search','description':'Search','description_clipped':False,'schema':{'type':'object'},'schema_status':'available','annotations':{'readOnlyHint':True},'output_schema_status':'available','output_schema':{'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Search','command':'search','args':[],'enabled':True};bridge.cache_scope='account-one'
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[],'structuredContent':{'count':'bad'}}},{'call_result':{'content':[],'structuredContent':{'count':2}}}]
            args={'tool':'search','arguments':'{"query":"same"}'};bodies=[]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',args)],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',args,'second')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Search',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual([x.args[0] for x in bridge.request.call_args_list],['discover','call','call'])
            self.assertTrue(any('failed validation' in m.get('content','') for m in bodies[2]['messages'] if m.get('role')=='tool'))
            self.assertNotIn('"count": "bad"',json.dumps(bodies[2]));self.assertEqual(events[-1]['status'],'completed')
            self.assertFalse(any(e['kind']=='operation_proposal' for e in events))

    def test_local_mcp_model_requests_require_start_and_call_approvals(self):
        from unittest.mock import Mock
        detail={'name':'query','description':'Run query','description_clipped':False,'schema':{'$schema':'http://json-schema.org/draft-07/schema#','type':'object','definitions':{'statement':{'anyOf':[{'type':'string','minLength':1},{'type':'null'}]}},'properties':{'sql':{'$ref':'#/definitions/statement'}},'required':['sql'],'additionalProperties':False},'schema_status':'available','annotations':{'readOnlyHint':True}}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Local DB','command':'server','args':[],'enabled':True}
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'text','text':'answer'}]}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'query','arguments':'{"sql":"SELECT 1"}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Query',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertFalse(any(e['kind']=='operation_proposal' for e in events))
            self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],['discover','call'])
            self.assertEqual(bridge.request.call_args_list[1].args[1]['arguments'],{'sql':'SELECT 1'})
            self.assertEqual(events[-1]['status'],'completed');bridge.close_signal.emit.assert_called_once()

    def test_large_mcp_result_reaches_coding_model(self):
        from unittest.mock import Mock
        detail={'name':'query','description':'Query','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Database','command':'server','args':[],'enabled':True};bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'text','text':'x'*500000+'END'}]}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'query','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[]
            def send(c,url,body,timeout):bodies.append(json.dumps(body));return replies.pop(0)
            events=[]
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),directory,'Query',mcp_bridge=bridge).run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertIn('x'*500000+'END',bodies[-1])

    def test_multiple_mcp_servers_route_colliding_names_independently(self):
        from unittest.mock import Mock
        tool={'name':'query','description':'Read','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as directory:
            first=Mock();first.server={'name':'Database','command':'server','args':[],'enabled':True};first.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'text','text':'database'}]}}]
            second=Mock();second.server={'name':'Search','transport':'http','url':'https://example.com/mcp','credential_id':'opaque','enabled':True};second.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'text','text':'search'}]}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{'server':'Database'}),call('mcp_discover',{'server':'Search'},'two')],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'server':'Search','tool':'query','arguments':'{}'}),call('mcp_call',{'server':'Database','tool':'query','arguments':'{}'},'db'),call('mcp_call',{'server':'Other','tool':'query','arguments':'{}'},'other')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Use both',mcp_bridges=[first,second]);events=[];bodies=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            approvals=[e['proposal'] for e in events if e['kind']=='operation_proposal'];self.assertEqual(approvals,[])
            self.assertEqual([entry.args[0] for entry in first.request.call_args_list],['discover','call']);self.assertEqual([entry.args[0] for entry in second.request.call_args_list],['discover','call'])
            self.assertTrue(any('exact selected MCP server' in m.get('content','') for m in bodies[-1]['messages'] if m.get('role')=='tool'));self.assertEqual(events[-1]['status'],'completed')
            first.close_signal.emit.assert_called_once();second.close_signal.emit.assert_called_once()
            schemas={tool['function']['name']:tool['function']['parameters']['required'] for tool in bodies[0]['tools'] if tool['function']['name'].startswith('mcp_')};self.assertTrue(all('server' in fields for fields in schemas.values()))

    def test_mcp_run_approval_is_scoped_to_one_server_and_expires(self):
        from unittest.mock import Mock
        tool={'name':'modify','description':'Change data','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as directory:
            first=Mock();first.server={'name':'Database','command':'server','args':[],'enabled':True};first.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[]}},{'call_result':{'content':[]}}]
            second=Mock();second.server={'name':'Search','transport':'http','url':'https://example.com/mcp','credential_id':'opaque','enabled':True};second.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[]}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{'server':'Database'}),call('mcp_discover',{'server':'Search'},'two')],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'server':'Database','tool':'modify','arguments':'{}'}),call('mcp_call',{'server':'Database','tool':'modify','arguments':'{}'},'again'),call('mcp_call',{'server':'Search','tool':'modify','arguments':'{}'},'other')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Use both',mcp_bridges=[first,second]);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':
                    proposal=event['proposal'];scope='mcp_server_run' if proposal['server']=='Database' else 'once'
                    self.assertTrue(run.decide(event['fingerprint'],True,scope))
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            approvals=[e['proposal'] for e in events if e['kind']=='operation_proposal'];self.assertEqual(approvals,[])
            self.assertEqual(first.request.call_count,3);self.assertEqual(second.request.call_count,2);self.assertEqual(run.mcp_run_allowed,set());self.assertEqual(events[-1]['status'],'completed')

    def test_mcp_environment_values_are_excluded_from_model_results_and_calls(self):
        from unittest.mock import Mock
        secret='environment-secret-test';tool={'name':'query','description':'Query','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'DB','command':'server','args':[],'env':{'TOKEN':'MY_TOKEN'},'enabled':True};bridge.environment_values={'TOKEN':secret};bridge.request.return_value={'tool_details':[tool]}
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'query','arguments':json.dumps({'value':secret})})],finish='tool_calls'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Query',mcp_bridge=bridge);events=[];bodies=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(bridge.request.call_count,1);self.assertNotIn(secret,json.dumps(events));self.assertNotIn(secret,json.dumps(bodies));self.assertEqual(events[-1]['status'],'failed')

    def test_mcp_run_approval_does_not_bypass_argument_validation(self):
        from unittest.mock import Mock
        tool={'name':'query','description':'Query','description_clipped':False,'schema':{'type':'object','properties':{'value':{'type':'integer'}},'required':['value']},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'DB','command':'server','args':[],'enabled':True};bridge.request.return_value={'tool_details':[tool]}
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'query','arguments':'{"value":"invalid"}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Query',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':self.assertTrue(run.decide(event['fingerprint'],True,'mcp_server_run'))
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual(bridge.request.call_count,1);self.assertEqual(events[-1]['status'],'completed');self.assertFalse(any('MCP server allowed for this run:' in e.get('text','') for e in events))

    def test_mcp_run_approval_rejects_unrelated_operations_and_stale_fingerprints(self):
        from unittest.mock import Mock
        bridge=Mock();bridge.server={'name':'Server'}
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'test',mcp_bridge=bridge)
            run.pending=('id',{'operation':'run_shell','server':'Server'})
            self.assertFalse(run.decide('id',True,'mcp_server_run'));self.assertEqual(run.mcp_run_allowed,set())
            run.pending=('id',{'operation':'mcp_start','server':'Server'})
            self.assertFalse(run.decide('old',True,'mcp_server_run'));self.assertFalse(run.decide('id',False,'mcp_server_run'))
            self.assertTrue(run.decide('id',True,'mcp_server_run'));self.assertFalse(run.decide('id',True,'mcp_server_run'));run.stop();self.assertEqual(run.mcp_run_allowed,set())

    def test_multiple_mcp_servers_reject_duplicate_names(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            first=Mock();first.server={'name':'Server'};second=Mock();second.server={'name':'server'}
            with self.assertRaises(ValueError):CodingRun(dict(C,stream=False),directory,'test',mcp_bridges=[first,second])

    def test_mcp_local_resources_require_separate_approvals_and_exact_uri(self):
        from unittest.mock import Mock
        item={'uri':'test://one','name':'One','description':'Example','mimeType':'text/plain'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Local','command':'server','args':[],'enabled':True}
            bridge.request.side_effect=[{'tool_details':[],'capabilities':['resources']},{'resources':[item],'more_resources':False},{'contents':[{'uri':'test://one','text':'Evidence'}]}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_list_resources',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_read_resource',{'uri':'test://unlisted'}),call('mcp_read_resource',{'uri':'test://one'},'allowed')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Read resource',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual([e['proposal']['operation'] for e in events if e['kind']=='operation_proposal'],[])
            self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],['discover','resources_list','resources_read']);self.assertEqual(events[-1]['status'],'completed')

    def test_remote_resource_requests_use_approval_and_exact_uri(self):
        from unittest.mock import Mock
        item={'uri':'test://one','name':'One','description':'Example','mimeType':'text/plain'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'opaque','enabled':True}
            bridge.request.side_effect=[{'tool_details':[],'capabilities':['resources']},{'resources':[item]},{'contents':[{'uri':'test://one','text':'Evidence'}]}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_list_resources',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_read_resource',{'uri':'test://one'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Read remote resource',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            proposals=[e['proposal'] for e in events if e['kind']=='operation_proposal']
            self.assertEqual(proposals,[]);self.assertEqual(bridge.request.call_args.args[1]['uri'],'test://one');self.assertEqual(events[-1]['status'],'completed')

    def test_mcp_prompts_require_approval_and_remain_tool_results(self):
        from unittest.mock import Mock
        prompt={'name':'review','description':'Review code','arguments':[{'name':'code','description':'source','required':True}]}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'opaque','enabled':True}
            bridge.request.side_effect=[{'tool_details':[],'capabilities':['prompts']},{'prompts':[prompt]},{'messages':[{'role':'user','content':{'type':'text','text':'Review this'}}]}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_list_prompts',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_get_prompt',{'name':'review','arguments':'{}'}),call('mcp_get_prompt',{'name':'review','arguments':'{"code":"abc"}'},'ok')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Review',mcp_bridge=bridge);events=[];bodies=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            proposals=[e['proposal'] for e in events if e['kind']=='operation_proposal'];self.assertEqual(proposals,[]);self.assertEqual(bridge.request.call_args.args[1]['arguments'],{'code':'abc'})
            self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],['discover','prompts_list','prompts_get']);self.assertEqual(events[-1]['status'],'completed')
            self.assertTrue(any(message.get('role')=='tool' and 'untrusted' in message.get('content','').lower() and 'Review this' in message.get('content','') for message in bodies[-1]['messages']))

    def test_mcp_resource_template_approved_with_expanded_uri(self):
        from unittest.mock import Mock
        template={'uriTemplate':'test://item/{id}{?query,limit}','name':'Item','description':'','mimeType':'text/plain','supported':True,'variables':['id','query','limit']}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'opaque','enabled':True}
            bridge.request.side_effect=[{'tool_details':[],'capabilities':['resources']},{'templates':[template]},{'contents':[{'uri':'test://item/a%2Fb?limit=10','text':'Evidence'}]}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_list_resource_templates',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_read_resource_template',{'template':'test://item/{id}{?query,limit}','variables':'{"id":"a/b","limit":"10"}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Read',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            proposals=[e['proposal'] for e in events if e['kind']=='operation_proposal'];self.assertEqual(proposals,[]);self.assertEqual(bridge.request.call_args.args[1]['uri'],'test://item/a%2Fb?limit=10');self.assertEqual(events[-1]['status'],'completed')

    def test_mcp_task_required_tool_is_not_sent_or_approved(self):
        from unittest.mock import Mock
        detail={'name':'long_job','description':'Run job','description_clipped':False,'schema':{'type':'object'},'schema_status':'available','task_support':'required'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'DB','command':'server','args':[],'enabled':True};bridge.request.return_value={'tool_details':[detail]}
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'long_job','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Run',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual([e['proposal']['operation'] for e in events if e['kind']=='operation_proposal'],[]);self.assertEqual(bridge.request.call_count,1)
            self.assertEqual(events[-1]['status'],'completed')

    def test_remote_mcp_model_approves_connection_and_exact_call(self):
        from unittest.mock import Mock
        detail={'name':'search','description':'Search','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'opaque','enabled':True}
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'text','text':'found'}]}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'search','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Search',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            proposals=[e['proposal'] for e in events if e['kind']=='operation_proposal']
            self.assertEqual(proposals,[])
            self.assertNotIn('credential_id',str(events));self.assertEqual(events[-1]['status'],'completed')

    def test_mcp_rejected_call_and_invalid_arguments_never_execute(self):
        from unittest.mock import Mock
        detail={'name':'query','description':'Query','description_clipped':False,'schema':{'type':'object','properties':{'sql':{'type':'string'}},'required':['sql']},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'DB','command':'server','args':[],'enabled':True};bridge.request.return_value={'tool_details':[detail]}
            calls=[call('mcp_call',{'tool':'query','arguments':'{}'}),call('mcp_call',{'tool':'query','arguments':'{"sql":"SELECT 1"}'},'second')]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=calls,finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Query',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],event['proposal']['operation']=='mcp_start')
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual([e['proposal']['operation'] for e in events if e['kind']=='operation_proposal'],[])
            self.assertEqual(bridge.request.call_count,2)
            self.assertEqual(events[-1]['status'],'completed')

    def test_git_mutations_require_separate_approvals(self):
        from dulwich import porcelain
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=porcelain.init(directory)
            (root/'one.txt').write_text('old');porcelain.add(repo,['one.txt']);porcelain.commit(repo,message=b'Initial',author=b'Test <test@example.invalid>',committer=b'Test <test@example.invalid>',no_verify=True,sign=False)
            (root/'one.txt').write_text('new');events=[]
            replies=[Wire(chat(calls=[call('git_stage',{'paths':'["one.txt"]'}),call('git_unstage',{'paths':'["one.txt"]'},'unstage'),call('git_create_branch',{'name':'feature/model'},'branch')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Stage and branch')
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':
                    run.decide(event['fingerprint'],event['proposal']['operation']!='git_unstage')
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual(len([e for e in events if e['kind']=='operation_proposal']),3)
            self.assertIn(b'refs/heads/feature/model',repo.refs)
            from agentnik.git_service import GitService
            self.assertEqual(GitService(ProjectFiles(root)).inspect('git_status')['staged'],['one.txt'])
            self.assertEqual(events[-1]['status'],'completed');repo.close()

    def test_project_file_operations_apply_without_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'old.txt').write_text('old\n');events=[]
            replies=[Wire(chat(calls=[call('read_file',{'path':'old.txt'}),call('delete_file',{'path':'old.txt'},'delete'),call('create_directory',{'path':'new'},'mkdir')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Change files')
            def emit(event):
                events.append(event)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertFalse((root/'old.txt').exists());self.assertTrue((root/'new').is_dir())
            self.assertFalse(any(e['kind'] in ('operation_proposal','edit_proposal') for e in events))
            self.assertEqual(events[-1]['status'],'completed')

    def test_shell_runs_only_after_approval_and_redacts_output(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];bodies=[];replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo hello'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            run=CodingRun(dict(C,stream=False,api_key='model-secret'),directory,'Run a command')
            with patch.object(core,'open_request',side_effect=send),patch('agentnik.shell.execute',return_value={'exit_code':0,'output':'model-secret','truncated':False}) as execute:
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':
                        execute.assert_not_called();self.assertEqual(event['proposal']['command'],'echo hello');run.decide(event['fingerprint'],True)
                run.run(emit);execute.assert_called_once()
            self.assertEqual(events[-1]['status'],'completed')
            self.assertNotIn('model-secret',json.dumps(events)+json.dumps(bodies))
            self.assertIn('[redacted]',json.dumps(bodies[1]))

    def test_shell_switch_applies_before_and_during_approval(self):
        for goal,initial,tool in ((False,True,'run_shell'),(False,False,'run_tests'),(True,True,'run_shell'),(True,False,'run_tests')):
            with self.subTest(goal=goal,initial=initial,tool=tool), tempfile.TemporaryDirectory() as directory:
                args={'path':'.','command':'echo hello'}
                if tool=='run_tests':args['format']='auto'
                replies=[Wire(chat(calls=[call(tool,args)],finish='tool_calls'),False),Wire(chat('Done'),False)]
                if goal:replies.extend([Wire(chat(calls=[call('set_goal_status',{'status':'completed','detail':'Command executed'})],finish='tool_calls'),False),Wire(chat('Done'),False)])
                run=CodingRun(dict(C,stream=False,api_key='model-secret'),directory,'Run a command',goal=goal);run.set_shell_without_approval(initial)
                events=[]
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':run.set_shell_without_approval(True)
                with patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute',return_value={'exit_code':0,'output':'model-secret','truncated':False}) as execute:
                    run.run(emit);execute.assert_called_once()
                self.assertEqual(any(e['kind']=='operation_proposal' for e in events),not initial)
                self.assertEqual(any(e['kind']=='shell_approval_resolved' for e in events),not initial)
                self.assertNotIn('model-secret',json.dumps(events));self.assertEqual(events[-1]['status'],'completed')

    def test_disabling_shell_switch_before_dispatch_requires_approval(self):
        for goal in (False,True):
            with self.subTest(goal=goal),tempfile.TemporaryDirectory() as directory:
                replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo test'})],finish='tool_calls'),False)]
                if goal:replies.append(Wire(chat(calls=[call('set_goal_status',{'status':'blocked','detail':'Command declined'})],finish='tool_calls'),False))
                replies.append(Wire(chat('Done'),False))
                run=CodingRun(dict(C,stream=False),directory,'Run a command',goal=goal);run.set_shell_without_approval(True)
                original=run.review_shell;events=[]
                def review(*args):
                    result=original(*args)
                    if run.shell_automatic_last:run.set_shell_without_approval(False)
                    return result
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':run.decide(event['fingerprint'],False)
                with patch.object(run,'review_shell',side_effect=review),patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute') as execute:
                    run.run(emit);execute.assert_not_called()
                self.assertTrue(any(e['kind']=='operation_proposal' for e in events));self.assertEqual(events[-1]['status'],'blocked' if goal else 'completed')

    def test_cancelling_pending_shell_is_not_released_by_switch(self):
        for goal in (False,True):
            with self.subTest(goal=goal),tempfile.TemporaryDirectory() as directory:
                replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo test'})],finish='tool_calls'),False)]
                run=CodingRun(dict(C,stream=False),directory,'Run a command',goal=goal);events=[]
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':run.stop();run.set_shell_without_approval(True)
                with patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute') as execute:
                    run.run(emit);execute.assert_not_called()
                self.assertTrue(any(e['kind']=='operation_proposal' for e in events))

    def test_project_edit_runs_before_rejected_shell_in_same_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];run=CodingRun(dict(C,stream=False),directory,'Create and test')
            replies=[Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'new'}),call('run_shell',{'path':'.','command':'echo test'},'shell')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':
                    self.assertEqual(Path(directory,'new.txt').read_text(),'new');self.assertEqual(event['proposal']['operation'],'run_shell')
                    run.decide(event['fingerprint'],False)
            with patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute') as execute:run.run(emit)
            execute.assert_not_called();self.assertEqual(events[-1]['status'],'completed');self.assertFalse(any(e['kind']=='edit_proposal' for e in events))

    def test_rejected_shell_command_does_not_start(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo denied'})],finish='tool_calls'),False),Wire(chat('Not run'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Run a command')
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],False)
            with patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute') as execute:
                run.run(emit);execute.assert_not_called()
            self.assertEqual(events[-1]['status'],'completed')

    def test_shell_rejects_visual_direction_controls_before_review(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];replies=[Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo \u202eevil'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            with patch.object(core,'open_request',side_effect=replies),patch('agentnik.shell.execute') as execute:
                CodingRun(dict(C,stream=False),directory,'Run a command').run(events.append)
                execute.assert_not_called()
            self.assertFalse(any(event['kind']=='operation_proposal' for event in events))
            self.assertEqual(events[-1]['status'],'completed')

    def test_invalid_arguments_reject_batch_and_allow_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            bodies=[];events=[]
            replies=[Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'first'}),call('read_file',{'path':42},'bad')],finish='tool_calls'),False),
                     Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'corrected'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(c,url,body,timeout):
                bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),directory,'Edit').run(events.append)
            self.assertEqual(Path(directory,'new.txt').read_text(),'corrected')
            self.assertIn('Every field must be a string',json.dumps(bodies[1]))
            self.assertIn('not executed',json.dumps(bodies[1]))
            self.assertEqual(events[-1]['status'],'completed')

    def test_google_block_allows_fetch_without_repeating_search(self):
        from agentnik.tools import ResearchError,Source
        with tempfile.TemporaryDirectory() as directory:
            bodies=[];events=[]
            replies=[Wire(chat(calls=[call('web_search',{'query':'library API'})],finish='tool_calls'),False),
                     Wire(chat(calls=[call('web_search',{'query':'try again'},'call-2'),call('web_fetch',{'url':'https://example.com/docs'},'call-3')],finish='tool_calls'),False),
                     Wire(chat('Reviewed documentation [S1]'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.code_agent.GoogleWeb') as google,patch('agentnik.code_agent.PublicWeb') as reader,patch.object(core,'open_request',side_effect=send):
                google.return_value.search.side_effect=ResearchError('Google Search blocked the request or requires a browser challenge')
                reader.return_value.fetch.return_value=[Source('','Docs','https://example.com/docs','documentation','now')]
                CodingRun(dict(C,stream=False),directory,'Research',web_enabled=True,search_provider='google').run(events.append)
                self.assertEqual(google.return_value.search.call_count,1);reader.return_value.fetch.assert_called_once()
            self.assertEqual(events[-1]['status'],'completed')
            first=json.loads(bodies[1]['messages'][-1]['content'])
            self.assertIn('unavailable for this run',first['error'])
            self.assertIn('do not retry',first['error'])
            self.assertTrue(any('direct public page reads remain available' in event.get('text','') for event in events))
            self.assertTrue(any('Source S1:' in event.get('text','') for event in events))

    def test_search_access_failure_keeps_sources_and_stops_retries(self):
        from agentnik.tools import AccessError,Source
        for error in (AccessError('Destination resolves to a restricted address'),core.EndpointError(403,'private provider response')):
            with self.subTest(error=type(error).__name__),tempfile.TemporaryDirectory() as directory:
                events=[];bodies=[];source=Source('','Public','https://example.com/','public result','now')
                searches=[call('web_search',{'query':'first'}),call('web_search',{'query':'second'},'two'),call('web_search',{'query':'blocked'},'three'),call('web_search',{'query':'retry'},'four')]
                replies=[Wire(chat(calls=searches,finish='tool_calls'),False),Wire(chat('Used available sources [S1]'),False)]
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch('agentnik.code_agent.OrderedSearch') as backend,patch.object(core,'open_request',side_effect=send):
                    backend.return_value.search.side_effect=[[source],[source],error]
                    run=CodingRun(dict(C,stream=False),directory,'Research',web_backends=[{'id':'brave','kind':'brave','name':'Brave','key':'private-key'}],web_enabled=True,search_provider='managed');run.run(events.append)
                self.assertEqual(backend.return_value.search.call_count,3);self.assertEqual(events[-1]['status'],'completed');self.assertEqual(len([e for e in events if e['kind']=='source']),2)
                outputs=[json.loads(m['content']) for m in bodies[-1]['messages'] if m.get('role')=='tool'];self.assertIn('do not retry',outputs[2]['error'].lower());self.assertIn('do not retry',outputs[3]['error'].lower());self.assertNotIn('private-key',json.dumps(events));self.assertTrue(any('Further searches are disabled' in e.get('text','') for e in events))
                if isinstance(error,core.EndpointError):self.assertTrue(any('HTTP 403' in e.get('text','') for e in events))

    def test_keyless_fetch_only_exposes_no_search_tool(self):
        from agentnik.tools import Source
        with tempfile.TemporaryDirectory() as directory:
            bodies=[];events=[]
            replies=[Wire(chat(calls=[call('web_fetch',{'url':'https://example.com/docs'})],finish='tool_calls'),False),Wire(chat('Read docs'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.code_agent.PublicWeb') as reader,patch.object(core,'open_request',side_effect=send):
                reader.return_value.fetch.return_value=[Source('','Docs','https://example.com/docs','text','now')]
                CodingRun(dict(C,stream=False),directory,'Read docs',web_enabled=True,search_provider='none').run(events.append)
            self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('web_fetch',json.dumps(bodies[0]['tools']));self.assertNotIn('web_search',json.dumps(bodies[0]['tools']))

    def test_custom_round_limit_stops_before_second_tool_batch(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits['rounds']=1;events=[];requests=[]
            def send(c,url,body,timeout):
                requests.append(body);return Wire(chat(calls=[call('list_files',{'path':'.'})],finish='tool_calls'),False)
            run=CodingRun(dict(C,stream=False),directory,'Inspect',limits=limits)
            limits['rounds']=8
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(len(requests),2)
            self.assertEqual(events[-1]['status'],'failed')
            self.assertIn('tool round limit',events[-1]['text'])
            self.assertTrue(events[-1]['limited'])

    def test_model_timeout_allows_slow_first_token_and_bounds_total_run(self):
        from agentnik.code_limits import coding_limits
        for seconds,total,expected in ((300,900,'completed'),(60,900,'failed'),(300,50,'failed')):
            with self.subTest(model_seconds=seconds,total=total),tempfile.TemporaryDirectory() as directory:
                limits=coding_limits();limits.update(model_seconds=seconds,turn_seconds=total)
                now=[0.0];events=[];timeouts=[]
                def send(c,url,body,timeout):
                    timeouts.append(timeout);now[0]=70.0
                    return Wire(chat('Local model finally replied'),False)
                with patch('agentnik.tools.time.monotonic',side_effect=lambda:now[0]),patch.object(core,'open_request',side_effect=send) as request:
                    CodingRun(dict(C,stream=False),directory,'Wait for local model',limits=limits).run(events.append)
                self.assertEqual(events[-1]['status'],expected);self.assertEqual(request.call_count,1)
                self.assertEqual(timeouts,[min(seconds,total)])


    def test_cancel_waiting_model_discards_late_response(self):
        with tempfile.TemporaryDirectory() as directory:
            started=threading.Event();release=threading.Event();returned=threading.Event();events=[]
            run=CodingRun(dict(C,stream=False),directory,'Wait')
            def send(c,url,body,timeout):
                started.set();release.wait(2);returned.set()
                return Wire(chat('Late response'),False)
            with patch.object(core,'open_request',side_effect=send) as request:
                worker=threading.Thread(target=run.run,args=(events.append,));worker.start()
                try:
                    self.assertTrue(started.wait(1));run.stop();worker.join(1)
                    self.assertFalse(worker.is_alive());snapshot=list(events)
                    release.set();self.assertTrue(returned.wait(1))
                    self.assertEqual(events,snapshot);self.assertEqual(request.call_count,1)
                    self.assertFalse(any(e['kind']=='finished' for e in events))
                finally:release.set();worker.join(2)

    def test_legacy_coding_limits_inherit_model_timeout_without_mutation(self):
        from agentnik.code_limits import coding_limits
        legacy=coding_limits();legacy.pop('model_seconds');legacy['turn_seconds']=300
        result=coding_limits(legacy)
        self.assertEqual(result['model_seconds'],300);self.assertEqual(result['turn_seconds'],300)
        self.assertNotIn('model_seconds',legacy)

    def test_coding_limits_reject_invalid_values(self):
        from agentnik.code_limits import coding_limits
        for bad in ({},{**coding_limits(),'calls':0},{**coding_limits(),'requests':True},{**coding_limits(),'turn_seconds':99999},{**coding_limits(),'model_seconds':0},{**coding_limits(),'model_seconds':True},{**coding_limits(),'model_seconds':3601}):
            with self.assertRaises(ValueError):coding_limits(bad)

    def test_shared_request_budget_stops_before_followup_model_call(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits['requests']=1;events=[];requests=[]
            def send(c,url,body,timeout):
                requests.append(body);return Wire(chat(calls=[call('list_files',{'path':'.'})],finish='tool_calls'),False)
            with patch.object(core,'open_request',side_effect=send):
                CodingRun(dict(C,stream=False),directory,'Inspect',limits=limits).run(events.append)
            self.assertEqual(len(requests),1);self.assertEqual(events[-1]['status'],'failed')
            self.assertIn('requests limit',events[-1]['text'])

    def test_web_research_is_opt_in_and_returns_untrusted_sources(self):
        from agentnik.tools import Source
        with tempfile.TemporaryDirectory() as directory:
            bodies=[];events=[]
            replies=[Wire(chat(calls=[call('web_search',{'query':'library API'})],finish='tool_calls'),False),Wire(chat(calls=[call('web_fetch',{'url':'https://example.com/docs'},'call-2')],finish='tool_calls'),False),Wire(chat('Found documentation [S2]'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            source=Source('','API reference','https://example.com/docs','untrusted page text search-secret','now')
            with patch('agentnik.code_agent.OrderedSearch') as backend,patch('agentnik.code_agent.PublicWeb') as reader,patch.object(core,'open_request',side_effect=send):
                backend.return_value.search.return_value=[source];reader.return_value.fetch.return_value=[source]
                run=CodingRun(dict(C,stream=False),directory,'Research',web_backends=[{'id':'search','kind':'ollama','key':'search-secret'}]);run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('web_search',json.dumps(bodies[0]['tools']))
            self.assertIn('untrusted evidence',json.dumps(bodies[1]))
            self.assertEqual(json.loads(bodies[1]['messages'][-1]['content'])['sources'][0]['id'],'S1')
            self.assertEqual(json.loads(bodies[2]['messages'][-1]['content'])['sources'][0]['id'],'S2')
            self.assertTrue(any('Source S1:' in event.get('text','') for event in events))
            self.assertTrue(any('Source S2:' in event.get('text','') for event in events))
            self.assertEqual([event['source']['id'] for event in events if event.get('kind')=='source'],['S1','S2'])
            self.assertIn('https://example.com/docs',json.dumps(events))
            self.assertNotIn('search-secret',json.dumps(bodies)+json.dumps(events))
            bodies.clear();events.clear()
            with patch.object(core,'open_request',side_effect=lambda c,url,body,timeout:(bodies.append(body) or Wire(chat('Done'),False))):
                CodingRun(dict(C,stream=False),directory,'No research').run(events.append)
            self.assertNotIn('web_search',json.dumps(bodies[0]['tools']))

    def test_cancel_during_web_search_discards_late_results(self):
        from agentnik.tools import Source
        with tempfile.TemporaryDirectory() as directory:
            started=threading.Event();release=threading.Event();events=[];requests=[]
            def send(c,url,body,timeout):
                requests.append(body);return Wire(chat(calls=[call('web_search',{'query':'API'})],finish='tool_calls'),False)
            def search(*args,**kwargs):
                started.set();release.wait(3)
                return [Source('','Late source','https://example.com/late','text','now')]
            with patch('agentnik.code_agent.OrderedSearch') as backend,patch.object(core,'open_request',side_effect=send):
                backend.return_value.search.side_effect=search
                run=CodingRun(dict(C,stream=False),directory,'Research',web_backends=[{'id':'search','kind':'ollama','key':'secret'}])
                thread=threading.Thread(target=run.run,args=(events.append,));thread.start()
                try:
                    self.assertTrue(started.wait(2));run.stop();thread.join(2)
                    self.assertFalse(thread.is_alive())
                finally:
                    release.set();thread.join(3)
            self.assertEqual(len(requests),1)
            self.assertFalse(any('Late source' in event.get('text','') for event in events))

    def test_web_failure_stops_without_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            events=[];requests=[]
            def send(c,url,body,timeout):
                requests.append(body);return Wire(chat(calls=[call('web_search',{'query':'API'})],finish='tool_calls'),False)
            with patch('agentnik.code_agent.OrderedSearch') as backend,patch.object(core,'open_request',side_effect=send):
                backend.return_value.search.side_effect=ValueError('search-secret')
                CodingRun(dict(C,stream=False),directory,'Research',web_backends=[{'id':'search','kind':'ollama','key':'search-secret'}]).run(events.append)
            self.assertEqual(len(requests),1)
            self.assertEqual(events[-1]['status'],'failed')
            self.assertIn('Web research stopped',events[-1]['text'])
            self.assertNotIn('search-secret',json.dumps(events))

    def test_explicit_previous_context_is_plain_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Follow up',context={'task':'Earlier task','answer':'Earlier answer'})
            bodies=[];events=[]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed')
            messages=bodies[0]['messages'];self.assertEqual([m['role'] for m in messages],['system','user','assistant','user'])
            self.assertEqual([m['content'] for m in messages[1:]],['Earlier task','Earlier answer','Follow up'])
            with self.assertRaises(ValueError):CodingRun(C,directory,'x',context={'task':'x'*2049,'answer':'y'})

    def test_project_search_returns_redacted_results_to_model(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'a.txt').write_text('needle private-key',encoding='utf-8')
            run=CodingRun(dict(C,stream=False,api_key='private-key'),directory,'Find needle');bodies=[];events=[]
            replies=[Wire(chat(calls=[call('search_project',{'path':'.','query':'needle'})],finish='tool_calls'),False),Wire(chat('Found'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('[redacted]',json.dumps(bodies[1]));self.assertNotIn('private-key',json.dumps(bodies[1]))

    def test_model_can_search_without_exposing_connection_key(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'a.txt').write_text('first\nneedle private-key\n',encoding='utf-8')
            run=CodingRun(dict(C,stream=False,api_key='private-key'),directory,'Find needle');bodies=[];events=[]
            replies=[Wire(chat(calls=[call('search_file',{'path':'a.txt','query':'needle'})],finish='tool_calls'),False),Wire(chat('Found'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('search_file',json.dumps(bodies[0]['tools']))
            self.assertIn('[redacted]',json.dumps(bodies[1]));self.assertNotIn('private-key',json.dumps(bodies[1]))

    def test_heavy_only_does_not_offer_or_accept_delegation(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Analyze');events=[];bodies=[]
            reply=Wire(chat(calls=[call('delegate_light',{'task':'Analyze'})],finish='tool_calls'),False)
            def send(c,url,body,timeout):bodies.append(body);return reply
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertNotIn('delegate_light',json.dumps(bodies[0]['tools']))
            self.assertEqual(events[-1]['status'],'failed')

    def test_multiple_files_apply_without_individual_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'a.txt').write_bytes(b'old a\n');Path(directory,'b.txt').write_bytes(b'old b\n')
            calls=[call('read_file',{'path':'a.txt'},'read-a'),call('read_file',{'path':'b.txt'},'read-b')]
            edits=[call('write_file',{'path':'a.txt','content':'new a\n'},'edit-a'),call('write_file',{'path':'b.txt','content':'new b\n'},'edit-b')]
            replies=[Wire(chat(calls=calls,finish='tool_calls'),False),Wire(chat(calls=edits,finish='tool_calls'),False),Wire(chat('Finished'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Update both');events=[]
            def emit(event):
                events.append(event)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertFalse(any(e['kind']=='edit_proposal' for e in events))
            self.assertEqual(Path(directory,'a.txt').read_bytes(),b'new a\n')
            self.assertEqual(Path(directory,'b.txt').read_bytes(),b'new b\n')
            self.assertEqual(events[-1]['status'],'completed')


    def test_failed_request_usage_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(C,directory,'Analyze');events=[]
            with patch('agentnik.compat_tools.request',side_effect=ValueError('failure')):run.run(events.append)
            self.assertEqual(events[-1]['status'],'failed')
            self.assertIn('Model: 1 request(s), input unknown, output unknown',events[-1]['usage'])

    def test_model_responses_include_optional_redacted_thinking(self):
        from types import SimpleNamespace
        for show in (False,True):
            with self.subTest(show=show),tempfile.TemporaryDirectory() as directory:
                run=CodingRun(dict(C,api_key='private-key'),directory,'Analyze');run.show_thinking=show;events=[];count=0
                def request(connection,body,runtime,emit,state):
                    nonlocal count
                    count+=1;state.update(text=('First private-key' if count==1 else 'Final'),thinking='Thought private-key',metrics={})
                    calls=[SimpleNamespace(name='list_files',arguments={'path':'.'},id='one',provider={})] if count==1 else []
                    return ({'role':'assistant','content':state['text']},calls)
                with patch('agentnik.compat_tools.request',side_effect=request):run.run(events.append)
                responses=[event for event in events if event['kind']=='model_response']
                self.assertEqual(len(responses),2);self.assertIn('[redacted]',responses[0]['text']);self.assertNotIn('private-key',json.dumps(events))
                self.assertEqual(responses[0]['thinking'],'Thought [redacted]' if show else '')
                self.assertTrue(events[-1]['response_shown']);self.assertEqual(events[-1]['text'],'Final')

    def test_chat_reads_approves_and_applies_real_temp_file_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'example.py';path.write_text('old\n')
            replies=[Wire(chat(calls=[call('read_file',{'path':'example.py'})],finish='tool_calls'),False),
                     Wire(chat(calls=[call('write_file',{'path':'example.py','content':'new\n'})],finish='tool_calls'),False),Wire(chat('Applied approved edit.'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Update example.py');events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='edit_proposal':self.assertTrue(run.decide(event['fingerprint'],True))
            with patch.object(core,'open_request',side_effect=replies) as endpoint,patch('subprocess.Popen') as process:run.run(emit)
            self.assertEqual(path.read_text(),'new\n');self.assertEqual(endpoint.call_count,3);process.assert_not_called()
            self.assertEqual(events[-1]['status'],'completed')

    def test_concurrent_edit_leaves_user_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'example.py';path.write_text('old\n');run=CodingRun(dict(C,stream=False),directory,'Update');events=[]
            replies=[Wire(chat(calls=[call('read_file',{'path':'example.py'})],finish='tool_calls'),False),Wire(chat(calls=[call('write_file',{'path':'example.py','content':'new\n'})],finish='tool_calls'),False),Wire(chat('Rejected.'),False)]
            def emit(event):
                events.append(event)
                if event.get('text','').startswith('Applying project edit:'):path.write_text('user change\n')
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual(path.read_text(),'user change\n')

    def test_multi_file_conflict_retains_first_edit_and_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            first=Path(directory,'a.txt');second=Path(directory,'b.txt')
            first.write_text('old a\n');second.write_text('old b\n')
            reads=[call('read_file',{'path':'a.txt'},'read-a'),call('read_file',{'path':'b.txt'},'read-b')]
            edits=[call('write_file',{'path':'a.txt','content':'new a\n'},'edit-a'),call('write_file',{'path':'b.txt','content':'new b\n'},'edit-b')]
            replies=[Wire(chat(calls=reads,finish='tool_calls'),False),Wire(chat(calls=edits,finish='tool_calls'),False),Wire(chat('Conflict noted.'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Update both');events=[];bodies=[]
            def emit(event):
                events.append(event)
                if event.get('text','').startswith('Applying project edit: b.txt'):second.write_text('user change\n')
            def send(connection,url,body,timeout):
                bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(first.read_text(),'new a\n');self.assertEqual(second.read_text(),'user change\n')
            results={item.get('tool_call_id'):json.loads(item['content']) for item in bodies[-1]['messages'] if item.get('role')=='tool'}
            self.assertTrue(results['edit-a']['applied']);self.assertIn('error',results['edit-b'])
            self.assertEqual(events[-1]['status'],'completed')

    def test_multi_file_cancellation_retains_only_completed_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            first=Path(directory,'a.txt');second=Path(directory,'b.txt')
            first.write_text('old a\n');second.write_text('old b\n')
            reads=[call('read_file',{'path':'a.txt'},'read-a'),call('read_file',{'path':'b.txt'},'read-b')]
            edits=[call('write_file',{'path':'a.txt','content':'new a\n'},'edit-a'),call('write_file',{'path':'b.txt','content':'new b\n'},'edit-b')]
            replies=[Wire(chat(calls=reads,finish='tool_calls'),False),Wire(chat(calls=edits,finish='tool_calls'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Update both')
            def emit(event):
                if event.get('text','').startswith('Applying project edit: b.txt'):run.stop()
            with patch.object(core,'open_request',side_effect=replies) as endpoint:run.run(emit)
            self.assertEqual(first.read_text(),'new a\n');self.assertEqual(second.read_text(),'old b\n')
            self.assertEqual(endpoint.call_count,2)


    def test_known_connection_keys_are_not_sent_in_file_results(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'example.py').write_text('private-known-key')
            run=CodingRun(dict(C,stream=False,api_key='private-known-key'),directory,'Inspect file')
            replies=[Wire(chat(calls=[call('read_file',{'path':'example.py'})],finish='tool_calls'),False),Wire(chat('Summary'),False)]
            bodies=[]
            def send(c,url,body,timeout):
                bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):run.run(lambda _:None)
            self.assertNotIn('private-known-key',json.dumps(bodies[-1]))
            self.assertIn('[redacted]',json.dumps(bodies[-1]))

    def test_edit_review_tokens_are_bound_to_the_run_and_denial_is_not_replayed(self):
        from agentnik.tools import Runtime
        with tempfile.TemporaryDirectory() as directory:
            proposal=ProjectFiles(directory).proposal('new.txt','new')
            run=CodingRun(C,directory,'Create');events=[]
            def reject(event):events.append(event);run.decide(event['fingerprint'],False)
            self.assertFalse(run.review(proposal,reject,Runtime()))
            self.assertFalse(run.review(proposal,reject,Runtime()));self.assertEqual(len(events),1)
            another=CodingRun(C,directory,'Create')
            def approve(event):
                self.assertFalse(another.decide(events[0]['fingerprint'],True));another.decide(event['fingerprint'],True)
            self.assertTrue(another.review(proposal,approve,Runtime()))

    def test_messages_and_native_models_can_apply_approved_edits(self):
        from test_research import Response,answer,call as native_call
        for protocol,url in [('messages','https://gateway.example/v1'),('chat','http://localhost:11434/v1')]:
            with self.subTest(protocol=protocol),tempfile.TemporaryDirectory() as directory:
                args={'path':'created.txt','content':'approved'}
                if protocol=='messages':
                    replies=[Wire(msg([{'type':'tool_use','id':'edit-1','name':'write_file','input':args}],'tool_use'),False),Wire(msg([{'type':'text','text':'Done'}]),False)]
                else:replies=[Response([answer('',[native_call('write_file',args)])]),Response([answer('Done')])]
                run=CodingRun(dict(C,protocol=protocol,url=url,stream=False),directory,'Create file');events=[];bodies=[]
                def emit(event):
                    events.append(event)
                    if event['kind']=='edit_proposal':run.decide(event['fingerprint'],True)
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):run.run(emit)
                self.assertEqual(events[-1]['status'],'completed')
                self.assertEqual(Path(directory,'created.txt').read_text(),'approved')
                if protocol=='messages':self.assertEqual(bodies[-1]['messages'][-1]['content'][0]['tool_use_id'],'edit-1')
                else:self.assertEqual(bodies[-1]['messages'][-1]['tool_call_id'],'call-0')


    def test_cancel_before_write_never_applies_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Create file')
            replies=[Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'hello'})],finish='tool_calls'),False)]
            def emit(event):
                if event.get('text','').startswith('Applying project edit:'):run.stop()
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertFalse((Path(directory)/'new.txt').exists())

if __name__=='__main__':unittest.main()

"""Agentnik coding through existing model protocols, using mock endpoints only."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentnik import core
from agentnik.code_agent import ProjectFiles,CodingRun
from test_routing import Wire,response,function_call,message
from test_compat_tools import chat,msg

C={'url':'https://gateway.example/v1','protocol':'chat','model':'heavy'}

def call(name,args,ident='call-1'):
    return {'id':ident,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}

class ProjectBoundaries(unittest.TestCase):
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
    def test_usage_is_attributed_to_roles_and_missing_counts_are_visible(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C),directory,'Analyze',dict(C,model='light'));events=[]
            responses=[({'input_tokens':10,'output_tokens':2},[SimpleNamespace(name='delegate_light',arguments={'task':'Check'},id='one',provider={})]),
                       ({'input_tokens':3,'output_tokens':0},[]),({},[])]
            def request(connection,body,runtime,emit,state):
                metrics,calls=responses.pop(0);state.update(metrics=metrics,text='Done')
                return ({'role':'assistant','content':'Done'},calls)
            with patch('agentnik.compat_tools.request',side_effect=request):run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('Heavy: 2 request(s), input 10 (known usage only), output 2 (known usage only)',events[-1]['usage'])
            self.assertIn('Light: 1 request(s), input 3, output 0 tokens',events[-1]['usage'])

    def test_failed_request_usage_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(C,directory,'Analyze');events=[]
            with patch('agentnik.compat_tools.request',side_effect=ValueError('failure')):run.run(events.append)
            self.assertEqual(events[-1]['status'],'failed')
            self.assertIn('Heavy: 1 request(s), input unknown, output unknown',events[-1]['usage'])

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

    def test_rejected_edit_leaves_user_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'example.py';path.write_text('old\n');run=CodingRun(dict(C,stream=False),directory,'Update');events=[]
            replies=[Wire(chat(calls=[call('read_file',{'path':'example.py'})],finish='tool_calls'),False),Wire(chat(calls=[call('write_file',{'path':'example.py','content':'new\n'})],finish='tool_calls'),False),Wire(chat('Rejected.'),False)]
            def emit(event):
                events.append(event)
                if event['kind']=='edit_proposal':run.decide(event['fingerprint'],False)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual(path.read_text(),'old\n')

    def test_heavy_can_delegate_to_light_using_a_different_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,protocol='responses',stream=False),directory,'Analyze',dict(C,protocol='messages',model='light',stream=False))
            fc=dict(function_call(),name='delegate_light',arguments=json.dumps({'task':'Suggest a simple test'}))
            bodies=[];replies=[Wire(response([fc]),False),Wire(msg([{'type':'text','text':'Use a unit test.'}]),False),Wire(response([message('Summary')]),False)]
            def send(c,url,body,timeout):bodies.append((c['model'],body));return replies.pop(0)
            events=[]
            with patch.object(core,'open_request',side_effect=send):run.run(events.append)
            self.assertEqual([name for name,_ in bodies],['heavy','light','heavy'])
            self.assertNotIn('tools',bodies[1][1]);self.assertIn('Use a unit test.',json.dumps(bodies[2][1]))
            self.assertEqual(events[-1]['status'],'completed')

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

    def test_light_endpoint_failure_stops_without_replaying_the_heavy_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Analyze',dict(C,model='light',stream=False))
            first=Wire(chat(calls=[call('delegate_light',{'task':'Analyze this task'})],finish='tool_calls'),False)
            events=[]
            with patch.object(core,'open_request',side_effect=[first,core.EndpointError(401,'private-body')]) as endpoint:run.run(events.append)
            self.assertEqual(endpoint.call_count,2);self.assertEqual(events[-1]['status'],'failed')
            self.assertNotIn('private-body',json.dumps(events))

    def test_cancel_during_review_never_applies_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Create file')
            replies=[Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'hello'})],finish='tool_calls'),False)]
            def emit(event):
                if event['kind']=='edit_proposal':run.stop()
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertFalse((Path(directory)/'new.txt').exists())

if __name__=='__main__':unittest.main()

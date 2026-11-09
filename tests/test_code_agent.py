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
    def test_web_research_is_opt_in_and_returns_untrusted_sources(self):
        from agentnik.tools import Source
        with tempfile.TemporaryDirectory() as directory:
            bodies=[];events=[]
            replies=[Wire(chat(calls=[call('web_search',{'query':'library API'})],finish='tool_calls'),False),Wire(chat('Found documentation'),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            source=Source('','API reference','https://example.com/docs','untrusted page text','now')
            with patch('agentnik.code_agent.OrderedSearch') as backend,patch.object(core,'open_request',side_effect=send):
                backend.return_value.search.return_value=[source]
                run=CodingRun(dict(C,stream=False),directory,'Research',web_backends=[{'id':'search','kind':'ollama','key':'search-secret'}]);run.run(events.append)
            self.assertEqual(events[-1]['status'],'completed')
            self.assertIn('web_search',json.dumps(bodies[0]['tools']))
            self.assertIn('untrusted evidence',json.dumps(bodies[1]))
            self.assertIn('https://example.com/docs',json.dumps(events))
            self.assertNotIn('search-secret',json.dumps(bodies)+json.dumps(events))
            bodies.clear();events.clear()
            with patch.object(core,'open_request',side_effect=lambda c,url,body,timeout:(bodies.append(body) or Wire(chat('Done'),False))):
                CodingRun(dict(C,stream=False),directory,'No research').run(events.append)
            self.assertNotIn('web_search',json.dumps(bodies[0]['tools']))

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

    def test_multiple_files_require_independent_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'a.txt').write_bytes(b'old a\n');Path(directory,'b.txt').write_bytes(b'old b\n')
            calls=[call('read_file',{'path':'a.txt'},'read-a'),call('read_file',{'path':'b.txt'},'read-b')]
            edits=[call('write_file',{'path':'a.txt','content':'new a\n'},'edit-a'),call('write_file',{'path':'b.txt','content':'new b\n'},'edit-b')]
            replies=[Wire(chat(calls=calls,finish='tool_calls'),False),Wire(chat(calls=edits,finish='tool_calls'),False),Wire(chat('Finished'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Update both');events=[];reviewed=[]
            def emit(event):
                events.append(event)
                if event['kind']=='edit_proposal':
                    reviewed.append(event['proposal']['path']);run.decide(event['fingerprint'],len(reviewed)==1)
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual(reviewed,['a.txt','b.txt'])
            self.assertEqual(Path(directory,'a.txt').read_bytes(),b'new a\n')
            self.assertEqual(Path(directory,'b.txt').read_bytes(),b'old b\n')
            self.assertEqual(events[-1]['status'],'completed')

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

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
    def setUp(self):
        from agentnik import search_cache
        search_cache._entries.clear()

    def tearDown(self):
        from agentnik import search_cache
        search_cache._entries.clear()

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
            self.assertEqual([e['proposal']['operation'] for e in events if e['kind']=='operation_proposal'],['mcp_start','mcp_call'])
            self.assertEqual([e['proposal'] for e in events if e['kind']=='operation_proposal'][-1]['annotations'],{'readOnlyHint':True})
            self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],['discover','call'])
            self.assertEqual(bridge.request.call_args_list[1].args[1]['arguments'],{'sql':'SELECT 1'})
            self.assertEqual(events[-1]['status'],'completed');bridge.close_signal.emit.assert_called_once()

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
            approvals=[e['proposal'] for e in events if e['kind']=='operation_proposal'];self.assertEqual([p['server'] for p in approvals],['Database','Search','Search','Database'])
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
            approvals=[e['proposal'] for e in events if e['kind']=='operation_proposal'];self.assertEqual([(p['operation'],p['server']) for p in approvals],[('mcp_start','Database'),('mcp_connect','Search'),('mcp_call_remote','Search')])
            self.assertEqual(first.request.call_count,3);self.assertEqual(second.request.call_count,2);self.assertEqual(len([e for e in events if 'MCP server allowed for this run:' in e.get('text','')]),2);self.assertEqual(run.mcp_run_allowed,set());self.assertEqual(events[-1]['status'],'completed')

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
            self.assertEqual([e['proposal']['operation'] for e in events if e['kind']=='operation_proposal'],['mcp_start','mcp_list_resources','mcp_read_resource'])
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
            self.assertEqual([p['operation'] for p in proposals],['mcp_connect','mcp_list_resources','mcp_read_resource']);self.assertEqual(proposals[-1]['url'],'https://example.com/mcp');self.assertEqual(proposals[-1]['resource']['uri'],'test://one');self.assertNotIn('credential_id',str(proposals));self.assertEqual(events[-1]['status'],'completed')

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
            proposals=[e['proposal'] for e in events if e['kind']=='operation_proposal'];self.assertEqual([p['operation'] for p in proposals],['mcp_connect','mcp_list_prompts','mcp_get_prompt']);self.assertEqual(proposals[-1]['arguments'],{'code':'abc'})
            self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],['discover','prompts_list','prompts_get']);self.assertEqual(events[-1]['status'],'completed')
            self.assertTrue(any(message.get('role')=='tool' and 'untrusted' in message.get('content','').lower() and 'Review this' in message.get('content','') for message in bodies[-1]['messages']))

    def test_mcp_prompt_rejection_does_not_send_get(self):
        from unittest.mock import Mock
        prompt={'name':'review','description':'Review','arguments':[]}
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock();bridge.server={'name':'Local','command':'server','args':[],'enabled':True};bridge.request.side_effect=[{'tool_details':[],'capabilities':['prompts']},{'prompts':[prompt]}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_list_prompts',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_get_prompt',{'name':'review','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            run=CodingRun(dict(C,stream=False),directory,'Review',mcp_bridge=bridge);events=[]
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],event['proposal']['operation']!='mcp_get_prompt')
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],['discover','prompts_list']);self.assertEqual(events[-1]['status'],'completed')

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
            proposals=[e['proposal'] for e in events if e['kind']=='operation_proposal'];self.assertEqual([p['operation'] for p in proposals],['mcp_connect','mcp_list_resource_templates','mcp_read_resource_template']);self.assertEqual(proposals[-1]['uri'],'test://item/a%2Fb?limit=10');self.assertEqual(bridge.request.call_args.args[1]['uri'],'test://item/a%2Fb?limit=10');self.assertEqual(events[-1]['status'],'completed')

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
            self.assertEqual([e['proposal']['operation'] for e in events if e['kind']=='operation_proposal'],['mcp_start']);self.assertEqual(bridge.request.call_count,1)
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
            self.assertEqual([p['operation'] for p in proposals],['mcp_connect','mcp_call_remote'])
            self.assertEqual(proposals[1]['url'],'https://example.com/mcp');self.assertNotIn('credential_id',str(proposals));self.assertEqual(events[-1]['status'],'completed')

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
            self.assertEqual([e['proposal']['operation'] for e in events if e['kind']=='operation_proposal'],['mcp_start','mcp_call'])
            self.assertEqual(bridge.request.call_count,1)
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
            events=[];reply=Wire(chat(calls=[call('run_shell',{'path':'.','command':'echo \u202eevil'})],finish='tool_calls'),False)
            with patch.object(core,'open_request',return_value=reply),patch('agentnik.shell.execute') as execute:
                CodingRun(dict(C,stream=False),directory,'Run a command').run(events.append)
                execute.assert_not_called()
            self.assertFalse(any(event['kind']=='operation_proposal' for event in events))
            self.assertEqual(events[-1]['status'],'failed')

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

    def test_heavy_and_light_have_model_timeout_while_web_keeps_its_deadline(self):
        from agentnik.tools import Source
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as directory:
            limits=coding_limits();limits['model_seconds']=240;timeouts=[];events=[]
            replies=[Wire(chat(calls=[call('delegate_light',{'task':'Review API'}),call('web_fetch',{'url':'https://example.com/docs'},'web')],finish='tool_calls'),False),Wire(chat('Analysis'),False),Wire(chat('Done'),False)]
            def send(c,url,body,timeout):timeouts.append((c['model'],timeout));return replies.pop(0)
            def fetch(url,runtime):
                self.assertEqual(runtime.limits.request_seconds,45)
                return [Source('','Docs',url,'Documentation','now')]
            with patch.object(core,'open_request',side_effect=send),patch('agentnik.code_agent.PublicWeb') as reader:
                reader.return_value.fetch.side_effect=fetch
                CodingRun(dict(C,stream=False),directory,'Research',light=dict(C,model='light',stream=False),limits=limits,web_enabled=True,search_provider='none').run(events.append)
            self.assertEqual(events[-1]['status'],'completed')
            self.assertEqual([name for name,_ in timeouts],['heavy','light','heavy'])
            self.assertTrue(all(239<timeout<=240 for _,timeout in timeouts))

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

    def test_concurrent_edit_leaves_user_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'example.py';path.write_text('old\n');run=CodingRun(dict(C,stream=False),directory,'Update');events=[]
            replies=[Wire(chat(calls=[call('read_file',{'path':'example.py'})],finish='tool_calls'),False),Wire(chat(calls=[call('write_file',{'path':'example.py','content':'new\n'})],finish='tool_calls'),False),Wire(chat('Rejected.'),False)]
            def emit(event):
                events.append(event)
                if event.get('text','').startswith('Applying project edit:'):path.write_text('user change\n')
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertEqual(path.read_text(),'user change\n')

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

    def test_cancel_before_write_never_applies_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            run=CodingRun(dict(C,stream=False),directory,'Create file')
            replies=[Wire(chat(calls=[call('write_file',{'path':'new.txt','content':'hello'})],finish='tool_calls'),False)]
            def emit(event):
                if event.get('text','').startswith('Applying project edit:'):run.stop()
            with patch.object(core,'open_request',side_effect=replies):run.run(emit)
            self.assertFalse((Path(directory)/'new.txt').exists())

if __name__=='__main__':unittest.main()

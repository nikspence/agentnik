"""Offline Chat MCP integration: mocked model and disposable local server."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,Mock

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialog
from agentnik import core,research
from agentnik.storage import Store
from agentnik.ui import Window
from test_routing import Wire,response,message

C={'url':'https://example.com/v1','protocol':'responses','model':'test','stream':False}


def function(name,arguments,ident):
    return {'type':'function_call','id':'fc-'+ident,'call_id':ident,'name':name,'arguments':json.dumps(arguments),'status':'completed'}


class ChatMCPIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def settle(self,predicate):
        end=time.monotonic()+10
        while not predicate() and time.monotonic()<end:self.app.processEvents();time.sleep(.005)
        self.assertTrue(predicate());self.app.processEvents()

    def test_remote_controller_reviews_arguments_and_filters_user_content(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
        tool={'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object','properties':{'q':{'type':'string'}},'required':['q']}}
        bridge.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'text','text':'private-for-user','annotations':{'audience':['user']}},{'type':'text','text':'model-evidence'}]}}]
        proposals=[]
        def accept(request):proposals.append(request['proposal']);request['approved']=True;request['done'].set()
        controller.approval_requested.connect(accept);runtime=Runtime();events=[];runtime.notify=lambda *args:events.append(args)
        controller.invoke('mcp_discover',{'server':'connect'},runtime)
        result=controller.invoke('mcp_call',{'request':json.dumps({'tool':'query','arguments':{'q':'abc'}})},runtime)
        self.assertEqual(proposals,[]);self.assertEqual(bridge.request.call_args_list[-1].args[1]['arguments'],{'q':'abc'})
        self.assertNotIn('private-for-user',json.dumps(result));self.assertIn('model-evidence',json.dumps(result));self.assertIn('private-for-user',str(events))
        self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],['discover','call'])

    def test_tool_call_runs_without_approval(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}]
        def deny(request):request['approved']=False;request['done'].set()
        controller.approval_requested.connect(deny)
        bridge.request.return_value={'call_result':{'content':[]}}
        result=controller.invoke('mcp_call',{'request':json.dumps({'tool':'query','arguments':{}})},Runtime())
        self.assertIn('result',result);bridge.request.assert_called_once()

    def test_activity_names_tool_and_outcome_without_arguments_or_result(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}]
        controller.bridge.request.side_effect=[{'call_result':{'content':[{'type':'text','text':'private-result'}]}},{'call_result':{'isError':True,'content':[{'type':'text','text':'private-error'}]}}]
        events=[];runtime=Runtime();runtime.notify=lambda kind,detail:events.append((kind,detail))
        for _ in range(2):controller.invoke('mcp_call',{'request':json.dumps({'tool':'query','arguments':{'sql':'private-query'}})},runtime)
        details='\n'.join(detail for _,detail in events)
        self.assertIn('Calling query on Remote.',details);self.assertIn('Tool query completed.',details);self.assertIn('Tool query reported an error.',details)
        self.assertNotIn('private-query',details);self.assertNotIn('private-result',details);self.assertNotIn('private-error',details)

    def test_activity_reports_uncertain_tool_call_without_retrying(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime,ResearchError
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        controller.tools=[{'name':'write','description':'Write','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}]
        controller.bridge.request.return_value={'error':'Connection closed','call_uncertain':True}
        events=[];runtime=Runtime();runtime.notify=lambda kind,detail:events.append(detail)
        with self.assertRaisesRegex(ResearchError,'may have completed'):
            controller.invoke('mcp_call',{'request':json.dumps({'tool':'write','arguments':{}})},runtime)
        controller.bridge.request.assert_called_once();self.assertIn('Tool write failed. The call may have completed; inspect server state before retrying.',events)

    def test_nested_arguments_cannot_send_inference_or_mapped_credentials(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime,ResearchError
        secret='secret"with\\slashes'
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]},extra_secrets=(secret,));bridge=Mock();controller.bridge=bridge
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}]
        with self.assertRaises(ResearchError):controller.invoke('mcp_call',{'request':json.dumps({'tool':'query','arguments':{'nested':{'value':secret}}})},Runtime())
        bridge.request.assert_not_called()

    def test_credentials_are_redacted_from_untrusted_object_keys(self):
        value={'content':[{'text':'prefix-secret-fixture','nested':{'secret-fixture':'secret-fixture'}}]}
        sanitized=research.scrub(value,('secret-fixture',))
        self.assertNotIn('secret-fixture',json.dumps(sanitized));self.assertIn('[redacted]',json.dumps(sanitized))

    def test_batch_validation_happens_before_server_actions(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import ResearchError
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
        good={'request':json.dumps({'tool':'query','arguments':{'value':1}})}
        bad={'request':json.dumps({'tool':'query','arguments':{'value':'wrong'}})}
        with self.assertRaises(ResearchError):controller.validate_batch([('mcp_discover',{'server':'connect'}),('mcp_call',good)])
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object','properties':{'value':{'type':'integer'}}}}]
        with self.assertRaises(ResearchError):controller.validate_batch([('mcp_call',good),('mcp_call',bad)])
        bridge.request.assert_not_called()

    def test_discovery_accepts_only_selected_server_name_or_connect(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import ResearchError
        server={'name':'Parquet','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]})
        for name in ('connect','Parquet','PARQUET'):
            controller.validate_batch([('mcp_discover',{'server':name})])
        with self.assertRaises(ResearchError):controller.validate_batch([('mcp_discover',{'server':'Other'})])

    def test_mcp_server_error_is_recorded_and_returned_to_model(self):
        import threading
        from agentnik.tools import ToolDefinition
        class FakeMCP:
            secret_values=[]
            definitions=(ToolDefinition('mcp_call','request','Call.',200),)
            def invoke(self,name,args,runtime):return {'result':{'isError':True,'content':[{'type':'text','text':'fixture failure'}]},'notice':'fixture'}
            def validate_batch(self,calls):pass
        bodies=[]
        replies=[Wire(response([function('mcp_call',{'request':'{}'},'first')]),False),Wire(response([message('The query failed.')]),False)]
        def send(c,url,body,timeout):bodies.append(body);return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):
            result=research.run_managed(C,[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=FakeMCP())
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['research']['tool_records'][0]['status'],'failed')
        self.assertIn('tool_failed',[event['kind'] for event in result['research']['events']])
        self.assertIn('fixture failure',json.dumps(bodies[-1]))

    def test_invalid_batch_is_not_executed_and_model_can_correct_it(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        tool={'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object','properties':{'value':{'type':'integer'}},'required':['value']}}
        for reconnect in (False,True):
            with self.subTest(reconnect=reconnect):
                controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
                if reconnect:bridge.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'text','text':'ok'}]}}]
                else:controller.tools=[tool];bridge.request.return_value={'call_result':{'content':[{'type':'text','text':'ok'}]}}
                good=json.dumps({'tool':'query','arguments':{'value':1}});bad=json.dumps({'tool':'query','arguments':{'value':'bad'}})
                replies=[Wire(response([function('mcp_call',{'request':good},'first'),function('mcp_call',{'request':bad},'second')]),False),Wire(response([function('mcp_call',{'request':good},'corrected')]),False),Wire(response([message('Done')]),False)]
                bodies=[]
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):
                    result=research.run_managed(C,[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
                self.assertEqual(result['status'],'ok');self.assertEqual(result['text'],'Done')
                self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],(['discover','call'] if reconnect else ['call']))
                self.assertIn('No tools in this batch were executed',json.dumps(bodies[1]))
                self.assertEqual([r['status'] for r in result['research']['tool_records']],['failed','failed','completed'])

    def test_wrong_outer_argument_shape_is_returned_to_model(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        wrong={'request':{'tool':'query','arguments':{}}}
        replies=[Wire(response([function('mcp_call',wrong,'first')]),False),Wire(response([message('I could not form the request.')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):
            result=research.run_managed(C,[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');controller.bridge.request.assert_not_called()
        self.assertIn('Invalid request',json.dumps(bodies[-1]));self.assertEqual(result['research']['tool_records'][0]['status'],'failed')

    def test_mcp_continuation_across_other_chat_protocols(self):
        import threading
        from agentnik.tools import ToolDefinition
        from test_research import C as native,MESSAGES,Response,answer,call
        from test_compat_tools import chat,msg,chat_call
        class FakeMCP:
            secret_values=[]
            definitions=(ToolDefinition('mcp_discover','server','Connect.',200),)
            def invoke(self,name,args,runtime):return {'tools':['fixture']}
            def validate_batch(self,calls):pass
        one=chat_call();one['function'].update(name='mcp_discover',arguments='{"server":"connect"}')
        block={'type':'tool_use','id':'call-1','name':'mcp_discover','input':{'server':'connect'}}
        fixtures=[(dict(native,stream=False),[Response([answer('',[call('mcp_discover',{'server':'connect'})])],False),Response([answer('Done')],False)]),
                  ({'url':'https://example.com/v1','protocol':'chat','model':'test','stream':False},[Wire(chat(calls=[one],finish='tool_calls'),False),Wire(chat('Done'),False)]),
                  ({'url':'https://example.com/v1','protocol':'messages','model':'test','stream':False},[Wire(msg([block],'tool_use'),False),Wire(msg([{'type':'text','text':'Done'}]),False)])]
        for connection,replies in fixtures:
            with self.subTest(protocol=connection['protocol'],url=connection['url']),patch.object(core,'open_request',side_effect=replies):
                result=research.run_managed(connection,MESSAGES,'',lambda _:None,threading.Event(),web_tools=False,mcp=FakeMCP())
                self.assertEqual(result['status'],'ok');self.assertEqual(result['text'],'Done')

    def test_invalid_call_feedback_continues_across_chat_protocols(self):
        import threading
        from agentnik.tools import ToolDefinition,ResearchError
        from test_research import C as native,MESSAGES,Response,answer,call
        from test_compat_tools import chat,msg,chat_call
        class InvalidMCP:
            secret_values=[]
            definitions=(ToolDefinition('mcp_call','request','Call.',200),)
            def validate_batch(self,calls):raise ResearchError('Invalid fixture request')
            def invoke(self,*args):self.fail('Invalid request must not execute')
        one=chat_call();one['function'].update(name='mcp_call',arguments='{"request":"{}"}')
        block={'type':'tool_use','id':'call-1','name':'mcp_call','input':{'request':'{}'}}
        fixtures=[(dict(native,stream=False),[Response([answer('',[call('mcp_call',{'request':'{}'})])],False),Response([answer('Done')],False)]),
                  ({'url':'https://example.com/v1','protocol':'chat','model':'test','stream':False},[Wire(chat(calls=[one],finish='tool_calls'),False),Wire(chat('Done'),False)]),
                  ({'url':'https://example.com/v1','protocol':'messages','model':'test','stream':False},[Wire(msg([block],'tool_use'),False),Wire(msg([{'type':'text','text':'Done'}]),False)])]
        for connection,replies in fixtures:
            bodies=[]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with self.subTest(protocol=connection['protocol'],url=connection['url']),patch.object(core,'open_request',side_effect=send):
                result=research.run_managed(connection,MESSAGES,'',lambda _:None,threading.Event(),web_tools=False,mcp=InvalidMCP())
                self.assertEqual(result['status'],'ok');self.assertEqual(result['text'],'Done')
                self.assertIn('Invalid fixture request',json.dumps(bodies[-1]))

    def test_approved_responses_turn_persists_and_reopens_without_server_restart(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);marker=root/'calls';server=root/'server.py'
            server.write_text('''import json,sys,pathlib
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'count','description':'Count rows','inputSchema':{'type':'object','properties':{'table':{'type':'string'}},'required':['table']}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('called');result={'content':[{'type':'text','text':'Count: 42'}]}
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Database','command':sys.executable,'args':[str(server),str(marker)],'enabled':True}];store.flush()
            window=Window(store);window.connections={'test':dict(C)};bodies=[]
            request=json.dumps({'tool':'count','arguments':{'table':'ap'}})
            replies=[Wire(response([function('mcp_discover',{'server':'Database'},'first')]),False),Wire(response([function('mcp_call',{'request':request},'second')]),False),Wire(response([message('There are 42 rows.')]),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1)
                self.assertFalse(marker.exists());tab.composer.setPlainText('Count AP rows')
                with patch.object(core,'open_request',side_effect=send),patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted) as approvals:
                    tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(approvals.call_count,0);self.assertTrue(marker.exists());self.assertEqual(tab.session['messages'][-1]['text'],'There are 42 rows.')
                self.assertIn('Count: 42',json.dumps(bodies[-1]));self.assertEqual(tab.session['messages'][-1]['research']['status'],'completed')
                marker.unlink();tab.composer.setPlainText('Count again')
                replies.extend([Wire(response([function('mcp_call',{'request':request},'third')]),False),Wire(response([message('Still 42 rows.')]),False)])
                with patch.object(core,'open_request',side_effect=send),patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted) as approvals:
                    tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(approvals.call_count,0);self.assertTrue(marker.exists());self.assertEqual(tab.session['messages'][-1]['text'],'Still 42 rows.')
                self.assertIn('Reconnecting',str(tab.session['messages'][-1]['research']['events']))
                from agentnik.research_ui import ResearchDetails
                details=tab.findChildren(ResearchDetails)[-1]
                self.assertIn('MCP activity',details.toggle.text());self.assertIn('Calling count on Database.',details.activity.toPlainText());self.assertIn('Tool count completed.',details.activity.toPlainText())
                saved=next(item for item in store.list_sessions() if item['id']==tab.session['id'])
                marker.unlink();window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);self.app.processEvents()
                self.assertFalse(marker.exists());self.assertEqual(window.tabs.currentWidget().mcp_choice.currentData()['name'],'Database')
            finally:window.close();self.app.processEvents();store.db.close()

    def test_stale_selection_and_strict_navigation_do_not_submit(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(folder);server={'name':'Local','command':sys.executable,'args':[],'enabled':True};store.config['mcp_servers']=[server];store.flush()
            window=Window(store);window.connections={'test':dict(C)}
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.composer.setPlainText('Run')
                server['args']=['changed']
                with patch('agentnik.ui.error') as warning,patch.object(core,'open_request') as send:
                    tab.submit();self.assertIn('changed',str(warning.call_args.args[1]));send.assert_not_called()
                tab.refresh_chat_mcp();tab.mcp_choice.setCurrentIndex(1)
                from agentnik import routing
                routing.save_defaults(store.config,'test',C,'Agentnik only','strict_public')
                with patch('agentnik.ui.error') as warning,patch.object(core,'open_request') as send:
                    tab.submit();self.assertIn('Strict public-only',str(warning.call_args.args[1]));send.assert_not_called()
            finally:window.close();self.app.processEvents();store.db.close()


    def test_read_only_unknown_and_write_tools_need_no_approval(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
        def tool(name,annotations):return {'name':name,'description':'Fixture','description_clipped':False,'schema_status':'available','schema':{'type':'object'},'annotations':annotations}
        controller.tools=[tool('read',{'readOnlyHint':True}),tool('write',{'readOnlyHint':False}),tool('unknown',{})]
        bridge.request.return_value={'call_result':{'content':[]}}
        proposals=[]
        def deny(request):proposals.append(request['proposal']);request['approved']=False;request['done'].set()
        controller.approval_requested.connect(deny)
        for name in ('read','write','unknown'):
            controller.invoke('mcp_call',{'request':json.dumps({'tool':name,'arguments':{}})},Runtime())
        self.assertEqual(proposals,[]);self.assertEqual(bridge.request.call_count,3)

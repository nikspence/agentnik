"""Offline contract tests for Parallel specialized search APIs."""
import json
import threading
import unittest
from unittest.mock import Mock,patch
from agentnik.parallel_tools import ParallelTools,DEFINITIONS
from agentnik.tools import AccessError,ResearchError,Runtime,Limits

class ParallelSpecialSearch(unittest.TestCase):
    def invoke(self,name,request,data,limits=None):
        transport=Mock();transport.request.return_value=('https://api.parallel.ai','application/json',json.dumps(data).encode())
        tool=ParallelTools('secret-fixture',transport);runtime=Runtime(threading.Event(),limits or Limits())
        from agentnik.web import public_url
        with patch('agentnik.parallel_tools.resolve_public',side_effect=lambda url,runtime:(public_url(url),[])):
            result=tool.invoke(name,{'request':json.dumps(request)},runtime)
        return result,transport.request.call_args

    def test_place_search_retains_location_fields_and_uses_fixed_endpoint(self):
        result,call=self.invoke('parallel_place_search',{'query':'tacos','location':'Madison, WI','open_now':True},{'results':[{'name':'Place','url':'https://example.com/place','address':'Main St','rating':'good','opening_hours':{'monday':[]}}],'warnings':[{'message':'Check hours'}]})
        self.assertEqual(call.args[0],'https://api.parallel.ai/v1/places/search');self.assertFalse(call.kwargs['redirects'])
        self.assertEqual(json.loads(call.kwargs['body']),{'query':'tacos','location':'Madison, WI','max_results':5,'mode':'fast','open_now':True})
        self.assertEqual(call.kwargs['headers']['x-api-key'],'secret-fixture');self.assertEqual(result['results'][0]['address'],'Main St');self.assertEqual(result['warnings'],['Check hours'])

    def test_image_and_entity_shapes_and_public_urls(self):
        result,call=self.invoke('parallel_image_search',{'search_queries':['bridge sunset'],'objective':'bridge photos'},{'results':[{'title':'Bridge','image_url':'https://example.com/a.jpg','source_page_url':'http://127.0.0.1/private','width':640}]})
        self.assertEqual(call.args[0],'https://api.parallel.ai/v1/images/search');self.assertEqual(json.loads(call.kwargs['body'])['advanced_settings']['max_results'],5)
        self.assertEqual(result['results'][0]['image_url'],'https://example.com/a.jpg');self.assertNotIn('source_page_url',result['results'][0])
        result,call=self.invoke('parallel_entity_search',{'entity_type':'companies','objective':'AI companies'},{'entities':[{'name':'Example','url':'https://example.com','description':'Company'}]},Limits(results=2))
        self.assertEqual(call.args[0],'https://api.parallel.ai/v1beta/findall/entity-search');self.assertEqual(json.loads(call.kwargs['body'])['match_limit'],5);self.assertEqual(result['results'][0]['name'],'Example')

    def test_bad_arguments_and_key_reflection_are_blocked(self):
        transport=Mock();tool=ParallelTools('secret-fixture',transport);runtime=Runtime()
        for name,value in [('parallel_place_search',{'query':'x'}),('parallel_image_search',{'search_queries':[]}),('parallel_entity_search',{'entity_type':'places','objective':'x'})]:
            with self.subTest(name=name),self.assertRaises(ResearchError):tool.invoke(name,{'request':json.dumps(value)},runtime)
        with self.assertRaises(AccessError):tool.invoke('parallel_entity_search',{'request':json.dumps({'entity_type':'people','objective':'secret-fixture'})},runtime)
        transport.request.assert_not_called()
        transport.request.return_value=('','',b'{"entities":[{"name":"secret-fixture"}]}')
        with self.assertRaises(AccessError):tool.invoke('parallel_entity_search',{'request':json.dumps({'entity_type':'people','objective':'scientists'})},runtime)

    def test_optional_geography_and_results_are_bounded(self):
        _,call=self.invoke('parallel_place_search',{'query':'coffee','latitude':43.0,'longitude':-89.0,'max_results':100,'mode':'advanced'},{'results':[]},Limits(results=3))
        self.assertEqual(json.loads(call.kwargs['body']),{'query':'coffee','latitude':43.0,'longitude':-89.0,'max_results':3,'mode':'advanced'})
        _,call=self.invoke('parallel_image_search',{'search_queries':['bridge'],'location':'US','max_results':2},{'results':[]})
        self.assertEqual(json.loads(call.kwargs['body'])['advanced_settings'],{'max_results':2,'location':'us'})
        _,call=self.invoke('parallel_entity_search',{'entity_type':'people','objective':'scientists','match_limit':500},{'entities':[]},Limits(results=3))
        self.assertEqual(json.loads(call.kwargs['body'])['match_limit'],5)

    def test_cancelled_search_makes_no_request(self):
        cancel=threading.Event();cancel.set();transport=Mock();tool=ParallelTools('secret-fixture',transport)
        with self.assertRaises(InterruptedError):tool.invoke('parallel_place_search',{'request':json.dumps({'query':'coffee','location':'Madison'})},Runtime(cancel))
        transport.request.assert_not_called()

    def test_research_exposes_tools_only_with_parallel_profile(self):
        from agentnik import core,research
        from agentnik.web import OrderedSearch
        from test_routing import Wire,response,message
        c={'url':'https://example.com/v1','protocol':'responses','model':'test','stream':False};messages=[{'role':'user','text':'Find places','images':[]}]
        for specs,expected in [([{'id':'p','name':'Parallel','kind':'parallel','key':'secret-fixture'}],True),([],False)]:
            bodies=[]
            def send(c,url,body,timeout):bodies.append(body);return Wire(response([message('Done')]),False)
            with self.subTest(expected=expected),patch.object(core,'open_request',side_effect=send):
                result=research.run_managed(c,messages,'',lambda _:None,threading.Event(),backend=OrderedSearch(specs))
            names=[x['name'] for x in bodies[0]['tools']];self.assertEqual('parallel_place_search' in names,expected);self.assertEqual(result['status'],'ok')
            self.assertNotIn('secret-fixture',json.dumps(bodies))

    def test_responses_model_uses_place_tool_and_receives_result(self):
        from agentnik import core,research
        from agentnik.web import OrderedSearch
        from test_routing import Wire,response,message
        from test_chat_mcp import function
        c={'url':'https://example.com/v1','protocol':'responses','model':'test','stream':False};messages=[{'role':'user','text':'Find places','images':[]}]
        request=json.dumps({'query':'tacos','location':'Madison, WI'});bodies=[]
        replies=[Wire(response([function('parallel_place_search',{'request':request},'one')]),False),Wire(response([message('Found a place.')]),False)]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send),patch('agentnik.parallel_tools.ParallelTools.invoke',return_value={'results':[{'name':'Fixture Place'}]}):
            result=research.run_managed(c,messages,'',lambda _:None,threading.Event(),backend=OrderedSearch([{'id':'p','name':'Parallel','kind':'parallel','key':'secret-fixture'}]))
        self.assertEqual(result['status'],'ok');self.assertIn('Fixture Place',json.dumps(bodies[-1]));self.assertNotIn('secret-fixture',json.dumps(result))

    def test_code_model_uses_entity_tool(self):
        import tempfile
        from agentnik import core
        from agentnik.code_agent import CodingRun
        from test_code_agent import C
        from test_compat_tools import chat
        from test_routing import Wire
        req=json.dumps({'entity_type':'companies','objective':'AI companies'})
        call={'id':'one','type':'function','function':{'name':'parallel_entity_search','arguments':json.dumps({'request':req})}}
        replies=[Wire(chat(calls=[call],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'open_request',side_effect=send),patch('agentnik.parallel_tools.ParallelTools.invoke',return_value={'results':[{'name':'Fixture Company'}]}):
            run=CodingRun(dict(C,stream=False),folder,'Find companies',web_backends=[{'id':'p','name':'Parallel','kind':'parallel','key':'secret-fixture'}],web_enabled=True,search_provider='managed');run.run(events.append)
        self.assertEqual(events[-1]['status'],'completed');self.assertIn('Fixture Company',json.dumps(bodies[-1]));self.assertNotIn('secret-fixture',json.dumps(bodies))

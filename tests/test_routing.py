"""Offline milestone C hosted/Responses contracts and conservative route policies."""
from dataclasses import asdict
import io
import json
import threading
import unittest
from unittest.mock import MagicMock,patch
from agentnik import core,hosted,research,responses_tools,routing,web
from agentnik.citations import cited_markdown
from agentnik.tools import AccessError,Limits,Runtime,Source
from test_research import Backend,C as NATIVE,MESSAGES

C={'url':'https://api.openai.com/v1','protocol':'responses','model':'configured-test-model','stream':True}
SPECS=[{'id':'ollama-search','kind':'ollama','name':'Primary search','key':'web-test-key'}]


def config(c=C):
    data={}
    for field in ('managed_tools','hosted_search'): research.set_capability(data,c,'configured','user configured',field)
    return data


def message(text='Answer SOURCE',annotations=None):
    return {'type':'message','id':'msg-1','role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':text,'annotations':annotations or []}]}


def citation(start=7,end=13,url='https://example.com/'):
    return {'type':'url_citation','url':url,'title':'Example','start_index':start,'end_index':end}


def search_call():
    return {'type':'web_search_call','id':'search-1','status':'completed','action':{'type':'search','queries':['necessary query'],
            'sources':[{'type':'url','url':'https://example.com/'}]}}


def function_call(ident='call-1',arguments='{"query":"necessary query"}'):
    return {'type':'function_call','id':'fc-'+ident,'call_id':ident,'name':'web_search','arguments':arguments,'status':'completed'}


def response(output,usage=True,status='completed'):
    value={'id':'response-1','status':status,'output':output}
    if usage: value['usage']={'input_tokens':10,'output_tokens':4,'output_tokens_details':{'reasoning_tokens':1}}
    return value


class Wire(io.BytesIO):
    def __init__(self,data,stream=True):
        wire=''.join('data: '+json.dumps(v)+'\n\n' for v in data) if stream else json.dumps(data)
        super().__init__(wire.encode()); self.headers={'Content-Type':'text/event-stream' if stream else 'application/json'}


class HostedContracts(unittest.TestCase):
    def execute(self,wire,c=None,**kwargs):
        updates=[]
        with patch.object(core,'open_request',return_value=wire) as transport:
            result=hosted.run_hosted(c or C,MESSAGES,'web-test-key',updates.append,threading.Event(),**kwargs)
        return result,updates,transport

    def test_streaming_search_annotations_usage_and_stateless_continuation(self):
        reasoning={'type':'reasoning','id':'rs-1','summary':[],'encrypted_content':'opaque-continuation'}
        output=[reasoning,search_call(),message(annotations=[citation()])]
        events=[{'type':'response.created','response':{'id':'response-1','status':'in_progress'}},
                {'type':'response.web_search_call.searching','item_id':'search-1','output_index':1},
                {'type':'response.output_text.delta','output_index':2,'content_index':0,'delta':'Answer SOURCE'},
                {'type':'response.output_text.annotation.added','output_index':2,'content_index':0,'annotation':citation()},
                {'type':'response.completed','response':response(output)}]
        result,updates,transport=self.execute(Wire(events))
        self.assertEqual(result['status'],'ok'); self.assertEqual(result['metrics']['input_tokens'],10)
        self.assertEqual(result['research']['capability_state'],'verified')
        self.assertEqual(result['research']['annotations'][0]['source_id'],'S1')
        source=result['research']['sources'][0]
        self.assertTrue(source['metadata_only']); self.assertEqual(source['retrieved_at'],''); self.assertEqual(source['excerpt'],'')
        body=transport.call_args.args[2]; self.assertEqual(body['model'],C['model']); self.assertEqual(body['tools'],[{'type':'web_search'}])
        self.assertFalse(body['store']); self.assertIn('reasoning.encrypted_content',body['include'])
        self.assertNotIn('web-test-key',json.dumps(body)); self.assertEqual(result['research']['response_items'],output)
        follow=core.chat_body(C,MESSAGES+[dict(role='assistant',**result),{'role':'user','text':'Follow up'}])['input']
        self.assertIn(reasoning,follow); self.assertIn(search_call(),follow)
        self.assertIn('https://example.com/',cited_markdown(result['text'],result['research']))
        self.assertTrue(any(e['kind']=='searching' for u in updates for e in u['research']['events']))
        self.assertEqual(len(result['research']['provider_usage']),1)

    def test_nonstreaming_and_missing_usage_do_not_fabricate_counts(self):
        result,_,_=self.execute(Wire(response([message('Plain answer')],usage=False),False),dict(C,stream=False))
        self.assertEqual(result['status'],'ok'); self.assertNotIn('input_tokens',result['metrics'])
        self.assertFalse(result['metrics']['usage_complete']); self.assertEqual(result['research']['capability_state'],'configured')

    def test_gateway_gate_blocks_provider_tools_before_any_request(self):
        result,_,transport=self.execute(Wire([]),dict(C,url='https://gateway.example/v1'))
        self.assertEqual(result['status'],'failed'); transport.assert_not_called(); self.assertEqual(result['research']['failure']['kind'],'access')

    def test_failed_stream_preserves_partial_search_and_usage(self):
        events=[{'type':'response.web_search_call.searching','item_id':'search-1'},
                {'type':'response.output_text.delta','delta':'Partial'},
                {'type':'response.failed','response':response([search_call(),message('Partial')],status='failed')}]
        result,_,_=self.execute(Wire(events))
        self.assertEqual(result['status'],'failed'); self.assertEqual(result['text'],'Partial')
        self.assertEqual(result['metrics']['output_tokens'],4); self.assertFalse(result['research']['failure']['fallback_allowed'])
        self.assertEqual(len(result['research']['sources']),1)

    def test_private_sources_invalid_offsets_and_invented_markers(self):
        result,_,_=self.execute(Wire([{'type':'response.completed','response':response([search_call(),message(annotations=[citation(url='http://127.0.0.1/')])])}]))
        self.assertEqual(result['research']['failure']['kind'],'access')
        result,_,_=self.execute(Wire([{'type':'response.completed','response':response([search_call(),message(annotations=[citation(end=999)])])}]))
        self.assertEqual(result['research']['annotations'],[]); self.assertEqual(result['research']['unverified_annotations'],1)
        data=dict(result['research'],annotations=[])
        self.assertEqual(cited_markdown('Invented [S1]',data),'Invented [S1]')
        invented,_,_=self.execute(Wire([{'type':'response.completed','response':response([search_call(),message('Invented [S1]')])}]))
        self.assertEqual(invented['research']['unverified_citations'],['S1'])

    def test_disconnection_wire_limit_and_redacted_offsets_do_not_fallback(self):
        result,_,_=self.execute(Wire([{'type':'response.output_text.delta','delta':'Partial'}]))
        self.assertEqual(result['research']['failure']['kind'],'uncertain')
        result,_,_=self.execute(Wire([{'type':'response.completed','response':response([message('x'*200)])}]),limits=Limits(model_bytes=50))
        self.assertEqual(result['research']['status'],'limited')
        result,_,_=self.execute(Wire([{'type':'response.completed','response':response([message('web-test-key SOURCE',[citation(13,19)])])}]))
        self.assertNotIn('web-test-key',json.dumps(result)); self.assertEqual(result['research']['annotations'],[])


class ManagedResponses(unittest.TestCase):
    def test_streamed_multi_call_arguments_and_encrypted_reasoning_are_replayed(self):
        reasoning={'type':'reasoning','id':'r1','summary':[],'encrypted_content':'opaque'}
        first=function_call(); second=function_call('call-2')
        events=[{'type':'response.output_item.added','output_index':0,'item':reasoning},
                {'type':'response.output_item.added','output_index':1,'item':dict(first,arguments='')},
                {'type':'response.function_call_arguments.delta','output_index':1,'delta':'{"query":'},
                {'type':'response.function_call_arguments.delta','output_index':1,'delta':'"necessary query"}'},
                {'type':'response.output_item.done','output_index':1,'item':first},
                {'type':'response.completed','response':response([reasoning,first,second])}]
        backend=Backend(); bodies=[]; responses=[Wire(events),Wire([{'type':'response.completed','response':response([message('Done [S1] and [S2]')])}])]
        def send(c,url,body,timeout): bodies.append(json.loads(json.dumps(body))); return responses.pop(0)
        with patch.object(core,'open_request',side_effect=send):
            result=research.run_managed(C,MESSAGES,'key',lambda _:None,threading.Event(),backend=backend)
        self.assertEqual(result['status'],'ok'); self.assertEqual(len(backend.searches),2)
        self.assertEqual(result['metrics']['input_tokens'],20); self.assertEqual(result['metrics']['last_input_tokens'],10)
        self.assertEqual(bodies[0]['tools'][0]['type'],'function'); self.assertTrue(bodies[0]['tools'][0]['strict'])
        follow=bodies[1]['input']; self.assertIn(reasoning,follow)
        self.assertEqual([x['call_id'] for x in follow if x.get('type')=='function_call_output'],['call-1','call-2'])
        self.assertEqual(len(result['research']['response_items']),6)
        self.assertFalse(result['metrics'].get('generation_tps'))

    def test_malformed_duplicate_and_unregistered_calls_never_execute(self):
        for output in ([function_call(arguments='{bad')], [function_call(),function_call()], [dict(function_call(),name='shell')]):
            backend=Backend()
            with self.subTest(output=output),patch.object(core,'open_request',return_value=Wire([{'type':'response.completed','response':response(output)}])):
                result=research.run_managed(C,MESSAGES,'key',lambda _:None,threading.Event(),backend=backend)
            self.assertEqual(result['status'],'failed'); self.assertFalse(backend.searches)


def fake_result(route,kind=None,partial=False):
    usage={'model_requests':1,'input_tokens':2,'output_tokens':0,'usage_complete':True,'last_input_tokens':2}
    return {'text':'Partial' if partial else '', 'thinking':'','metrics':usage,'status':'failed' if kind else 'ok',
            'research':{'status':'failed' if kind else 'completed','events':[],'sources':[],'exchanges':[],
                        'attempts':[{'route':route,'status':'failed' if kind else 'completed'}],
                        'failure':{'kind':kind,'partial':partial,'fallback_allowed':not partial and kind in ('authentication','unsupported','rate_limit','temporary'),'retry_after':0},
                        'capability_state':'unsupported' if kind=='unsupported' else 'configured'}}


class RouteContracts(unittest.TestCase):
    def execute(self,policy='Provider first',first=None,managed=None,c=C,cfg=None,**kwargs):
        order=[]; identities=[]
        def h(c,*args,**kw): order.append('hosted'); identities.append(dict(c)); return first() if first else fake_result('hosted')
        def m(c,*args,**kw): order.append('managed'); identities.append(dict(c)); return managed() if managed else fake_result('managed')
        updates=[]
        with patch.object(hosted,'run_hosted',side_effect=h),patch.object(research,'run_managed',side_effect=m):
            result=routing.run(c,MESSAGES,'web-test-key',updates.append,threading.Event(),cfg or config(c),policy,SPECS,'public_fetch',**kwargs)
        return result,order,identities,updates

    def test_four_policies_order_and_single_route_behavior(self):
        for policy,expected in [('Provider first',['hosted']),('Agentnik first',['managed']),('Provider only',['hosted']),('Agentnik only',['managed'])]:
            with self.subTest(policy=policy):
                _,order,identities,_=self.execute(policy)
                self.assertEqual(order,expected); self.assertTrue(all(c==C for c in identities))
        result,order,_,_=self.execute('Provider only',first=lambda:fake_result('hosted','unsupported'))
        self.assertEqual(order,['hosted']); self.assertEqual(result['status'],'failed')

    def test_explicit_rejection_and_authentication_can_fallback_with_accounting(self):
        for kind in ('unsupported','authentication'):
            result,order,identities,updates=self.execute(first=lambda:fake_result('hosted',kind))
            self.assertEqual(order,['hosted','managed']); self.assertEqual(result['metrics']['input_tokens'],4)
            self.assertEqual(result['metrics']['model_requests'],2); self.assertTrue(all(c==C for c in identities))
            self.assertTrue(any(e['kind']=='route_switch' for e in result['research']['events']))
        self.assertEqual(result['research']['policy'],'Provider first')

    def test_rate_retry_is_bounded_then_next_route_no_cycle(self):
        result,order,_,_=self.execute(first=lambda:fake_result('hosted','rate_limit'))
        self.assertEqual(order,['hosted','hosted','managed']); self.assertEqual(result['metrics']['model_requests'],3)
        self.assertEqual(len(result['research']['attempts']),3)

    def test_partial_uncertain_cancel_access_and_unrelated_errors_never_fallback(self):
        for kind,partial in [('temporary',True),('uncertain',False),('cancelled',False),('access',False),('configuration',False)]:
            result,order,_,_=self.execute(first=lambda:fake_result('hosted',kind,partial))
            self.assertEqual(order,['hosted']); self.assertEqual(result['status'],'failed')

    def test_retry_after_longer_than_bound_stops_without_switch(self):
        def failed():
            value=fake_result('hosted','rate_limit'); value['research']['failure']['retry_after']=60; return value
        result,order,_,_=self.execute(first=failed)
        self.assertEqual(order,['hosted']); self.assertIn('bounded wait',result['error'])

    def test_skips_unknown_scoped_capability_and_native_hosted_without_probes(self):
        result,order,_,_=self.execute(c=NATIVE)
        self.assertEqual(order,['managed']); self.assertEqual(result['research']['attempts'][0]['status'],'skipped')
        cfg=config(); research.set_capability(cfg,C,'unknown','',field='hosted_search')
        _,order,_,_=self.execute(cfg=cfg); self.assertEqual(order,['managed'])
        cfg=config(dict(C,model='other'))
        _,order,_,_=self.execute(cfg=cfg); self.assertEqual(order,[])

    def test_strict_navigation_disables_external_routes_before_submission(self):
        with patch.object(hosted,'run_hosted') as h,patch.object(research,'run_managed') as m:
            result=routing.run(C,MESSAGES,'key',lambda _:None,threading.Event(),config(),'Provider first',SPECS,'strict_public')
        h.assert_not_called(); m.assert_not_called(); self.assertEqual(len(result['research']['attempts']),2)
        self.assertEqual(result['metrics']['model_requests'],0)

    def test_real_http_rejection_falls_back_to_responses_tools_without_changing_connection(self):
        rejection=core.EndpointError(400,json.dumps({'error':{'message':'web_search is not supported by this model','param':'tools','code':'unsupported_value'},'usage':{'input_tokens':3,'output_tokens':0}}))
        responses=[rejection,Wire([{'type':'response.completed','response':response([function_call()])}]),Wire([{'type':'response.completed','response':response([message('Evidence [S1]')])}])]
        connections=[]
        def send(c,url,body,timeout):
            connections.append((dict(c),url,json.loads(json.dumps(body))))
            value=responses.pop(0)
            if isinstance(value,Exception): raise value
            return value
        with patch.object(core,'open_request',side_effect=send):
            result=research.run(C,MESSAGES,'key',lambda _:None,threading.Event(),config=config(),policy='Provider first',backends=SPECS,backend=Backend())
        self.assertEqual(result['status'],'ok'); self.assertEqual(len(connections),3)
        self.assertTrue(all(c==C and url=='https://api.openai.com/v1/responses' for c,url,body in connections))
        self.assertEqual(result['metrics']['input_tokens'],23); self.assertEqual(result['metrics']['output_tokens'],8)
        self.assertEqual(result['research']['capability_updates'][0]['field'],'hosted_search')
        self.assertEqual(result['research']['capability_updates'][1]['field'],'managed_tools')

    def test_cancellation_during_retry_wait_stops_before_second_submission(self):
        cancel=threading.Event()
        def emit(value):
            if any(e['kind']=='retry_wait' for e in value['research']['events']): cancel.set()
        with patch.object(hosted,'run_hosted',return_value=fake_result('hosted','rate_limit')) as provider,patch.object(research,'run_managed') as managed:
            result=routing.run(C,MESSAGES,'key',emit,cancel,config(),'Provider first',SPECS,'public_fetch')
        provider.assert_called_once(); managed.assert_not_called()
        self.assertEqual(result['research']['status'],'cancelled'); self.assertEqual(result['metrics']['input_tokens'],2)

    def test_ambiguous_errors_are_not_tool_capability_evidence(self):
        from agentnik.failures import classify
        cases=[({'message':'unsupported parameter max_tool_calls','param':'max_tool_calls','code':'unsupported_parameter'},'configuration'),
               ({'message':'web_search parameters contain a property that is not supported','param':'tools','code':'invalid_schema'},'configuration'),
               ({'message':'web_search is not supported by this model','param':'tools','code':None},'unsupported')]
        for error,expected in cases:
            self.assertEqual(classify(core.EndpointError(400,json.dumps({'error':error})),tool='web_search')['kind'],expected)
        self.assertEqual(classify(core.EndpointError(500,'{}'))['kind'],'uncertain')

    def test_missing_latest_input_usage_is_unknown_not_earlier_context(self):
        values=[{'metrics':{'model_requests':1,'input_tokens':4,'output_tokens':1,'last_input_tokens':4,'usage_complete':True}},
                {'metrics':{'model_requests':1,'usage_complete':False}}]
        totals=routing.aggregate(values,Runtime())
        self.assertEqual(totals['input_tokens'],4); self.assertIsNone(totals['last_input_tokens']); self.assertFalse(totals['usage_complete'])

    def test_shared_request_budget_prevents_second_route_submission(self):
        rejection=core.EndpointError(400,json.dumps({'error':{'message':'web_search is not supported','param':'tools'}}))
        with patch.object(core,'open_request',side_effect=rejection) as send:
            result=research.run(C,MESSAGES,'key',lambda _:None,threading.Event(),config=config(),policy='Provider first',backends=SPECS,backend=Backend(),limits=Limits(requests=1))
        self.assertEqual(send.call_count,1); self.assertEqual(result['research']['status'],'limited')


class BackendContracts(unittest.TestCase):
    def test_ordered_credentials_skip_and_fallback_without_replaying_model(self):
        specs=[{'id':'missing','kind':'ollama','name':'Missing','key':''},
               {'id':'first','kind':'ollama','name':'First','key':'first-key'},
               {'id':'second','kind':'ollama','name':'Second','key':'second-key'}]
        events=[]; runtime=Runtime(); runtime.notify=lambda *e:events.append(e)
        first=MagicMock(); first.search.side_effect=core.EndpointError(401,'{}')
        second=Backend()
        with patch.object(web,'OllamaWeb',side_effect=[first,second]) as factory:
            service=web.OrderedSearch(specs); sources=service.search('query',runtime)
        self.assertEqual(factory.call_count,2); self.assertEqual(sources[0].backend,'second')
        self.assertEqual([a['status'] for a in service.attempts],['skipped','failed','completed'])
        self.assertTrue(any(e[0]=='backend_switch' for e in events))

    def test_duplicate_profiles_do_not_repeat_a_rejected_backend(self):
        specs=[dict(SPECS[0],id='a',key='a-key'),dict(SPECS[0],id='b',key='a-key')]
        first=MagicMock(); first.search.side_effect=core.EndpointError(401,'{}')
        with patch.object(web,'OllamaWeb',return_value=first) as factory,patch.object(web,'FirecrawlKeylessWeb',return_value=Backend()):
            service=web.OrderedSearch(specs)
            service.search('query',Runtime())
        self.assertEqual(factory.call_count,1); self.assertEqual(service.attempts[1]['status'],'skipped')

    def test_blocked_access_and_empty_results_do_not_try_another_backend(self):
        specs=[dict(SPECS[0],id='a',key='a-key'),dict(SPECS[0],id='b',key='b-key')]
        for outcome in (AccessError('blocked'),[]):
            first=MagicMock()
            if isinstance(outcome,Exception): first.search.side_effect=outcome
            else: first.search.return_value=outcome
            with patch.object(web,'OllamaWeb',return_value=first) as factory:
                if isinstance(outcome,Exception):
                    with self.assertRaises(AccessError): web.OrderedSearch(specs).search('query',Runtime())
                else: self.assertEqual(web.OrderedSearch(specs).search('query',Runtime()),[])
            self.assertEqual(factory.call_count,1)


if __name__=='__main__': unittest.main()

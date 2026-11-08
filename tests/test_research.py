"""Offline research contracts: execution, transport, provenance, and failure behavior."""
from dataclasses import asdict, replace
import io
import json
import socket
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from agentnik import core, ollama_tools, research, web
from agentnik.tools import AccessError, Capability, LimitError, Limits, Registry, Runtime, Source, ToolCall

C={'url':'http://localhost:11434/v1','protocol':'chat','model':'test'}
MESSAGES=[{'role':'user','text':'Find evidence','images':[]}]
PUBLIC=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
PRIVATE=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',80))]

class Response(io.BytesIO):
    def __init__(self,objects,stream=True):
        data=b''.join(json.dumps(o).encode()+b'\n' for o in objects) if stream else json.dumps(objects[0]).encode()
        super().__init__(data); self.headers={'Content-Type':'application/x-ndjson' if stream else 'application/json'}


def answer(text='Evidence [S1].',calls=None,thinking=''):
    return {'message':{'role':'assistant','content':text,'thinking':thinking,**({'tool_calls':calls} if calls else {})},
            'done':True,'prompt_eval_count':12,'eval_count':3,'eval_duration':1_000_000_000}


def call(name='web_search',args=None,index=0):
    return {'id':f'call-{index}','function':{'index':index,'name':name,'arguments':args or {'query':'query'}}}


class Backend:
    def __init__(self): self.searches=[]; self.fetches=[]
    def search(self,query,runtime):
        self.searches.append(query)
        return [Source('','Example','https://example.com/','Saved evidence', '2026-11-08T00:00:00+00:00',backend='fake')]
    def fetch(self,url,runtime):
        self.fetches.append(url)
        return [Source('','Page',url,'Readable text','2026-11-08T00:00:00+00:00',truncated=True,backend='fake')]


class ToolContracts(unittest.TestCase):
    def test_registry_rejects_unknown_and_invalid_arguments_before_execution(self):
        handler=MagicMock(); registry=Registry(handler,handler)
        for name,args in [('shell',{}),('web_search','{'),('web_search',{'query':False}),('web_search',{'query':'x','api_key':'bad'}),('web_search',{'query':' '}),('web_fetch',{'url':'a'*2049})]:
            with self.subTest(name=name,args=args), self.assertRaises(ValueError):
                registry.execute(ToolCall('1',name,args),Runtime())
        handler.assert_not_called()

    def test_argument_assembly_multiple_calls_ids_and_malformed_json(self):
        assembly=ollama_tools.CallAssembler(Limits())
        assembly.add([call(args='{"que')]); assembly.add([{'function':{'index':0,'arguments':'ry":"one"}'}}])
        assembly.add([call('web_fetch',{'url':'https://example.com'},1)])
        calls,wire=assembly.finish()
        self.assertEqual(calls[0].arguments,{'query':'one'}); self.assertEqual(calls[1].id,'call-1')
        self.assertEqual(wire[0]['function']['index'],0)
        broken=ollama_tools.CallAssembler(Limits()); broken.add([call(args='{')])
        with self.assertRaisesRegex(ValueError,'Malformed'): broken.finish()
        too_big=ollama_tools.CallAssembler(Limits(argument_bytes=10))
        with self.assertRaises(LimitError): too_big.add([call(args='x'*20)])

    def test_cancellation_deadlines_and_late_results(self):
        runtime=Runtime(limits=Limits(request_seconds=.025)); release=threading.Event()
        try:
            with self.assertRaises(LimitError): runtime.wait(lambda:release.wait(2))
            with self.assertRaises(LimitError): runtime.check()
        finally: release.set()
        cancel=threading.Event(); cancel.set()
        fn=MagicMock()
        with self.assertRaises(InterruptedError): Runtime(cancel).wait(fn)
        fn.assert_not_called()
        runtime=Runtime(limits=Limits(turn_seconds=.001)); runtime.started-=1
        with self.assertRaises(LimitError): runtime.check()

    def test_capability_is_endpoint_protocol_model_scoped(self):
        config={}; research.set_capability(config,C,'configured','user enabled')
        self.assertEqual(research.capability(config,C).state,'configured')
        for changes in ({'model':'other'},{'url':'http://localhost:11435/v1'},{'protocol':'responses'}):
            self.assertEqual(research.capability(config,dict(C,**changes)).state,'unknown')
        record=next(iter(config['research_capabilities'].values()))
        self.assertEqual(record['hosted_search']['state'],'unknown')
        with self.assertRaises(ValueError): Capability('assumed')


class LoopContracts(unittest.TestCase):
    def run_loop(self,responses,backend=None,**kwargs):
        backend=backend or Backend(); progress=[]; bodies=[]
        def transport(c,url,body,timeout):
            bodies.append(json.loads(json.dumps(body)))
            return responses.pop(0)
        with patch.object(core,'open_request',side_effect=transport):
            result=research.run(C,MESSAGES,'web-secret',progress.append,threading.Event(),backend=backend,**kwargs)
        return result,progress,bodies,backend

    def test_streamed_multi_call_loop_thinking_continuation_and_usage(self):
        first=Response([{'message':{'thinking':'Plan','tool_calls':[call(args='{"query":')]}},
                        answer('',[{'function':{'index':0,'arguments':'"one"}'}},call('web_fetch',{'url':'https://example.com/'},1)])])
        result,progress,bodies,backend=self.run_loop([first,Response([answer('Answer [S1], [S2], [S999].')])])
        self.assertEqual(result['status'],'ok'); self.assertEqual(result['thinking'],'Plan'); self.assertEqual(backend.searches,['one']); self.assertEqual(len(backend.fetches),1)
        follow=bodies[1]['messages']; self.assertEqual(follow[-3]['thinking'],'Plan')
        self.assertEqual(follow[-2]['role'],'tool'); self.assertEqual(follow[-2]['tool_call_id'],'call-0')
        self.assertEqual(result['metrics']['input_tokens'],24); self.assertEqual(result['metrics']['output_tokens'],6)
        self.assertEqual(result['metrics']['last_input_tokens'],12); self.assertTrue(result['metrics']['usage_complete'])
        self.assertEqual(result['research']['citations'],['S1','S2']); self.assertEqual(result['research']['unverified_citations'],['S999'])
        self.assertEqual(result['research']['capability_state'],'verified')
        self.assertTrue(all(p['research']['run_id']==result['research']['run_id'] for p in progress))
        messages=MESSAGES+[dict(role='assistant',**result)]
        self.assertEqual(core.chat_body(C,messages)['messages'][-1]['content'],result['text'])
        self.assertEqual(len(core.chat_body(C,messages)['messages']),5)
        self.assertEqual(bodies[0]['model'],bodies[1]['model'])

    def test_nonstreaming_round(self):
        c=dict(C,stream=False)
        with patch.object(core,'open_request',return_value=Response([answer('No search needed')],False)):
            result=research.run(c,MESSAGES,'key',lambda _:None,threading.Event(),backend=Backend())
        self.assertEqual(result['status'],'ok'); self.assertEqual(result['research']['capability_state'],'configured')

    def test_failed_second_request_retains_sources_usage_and_partial_output_no_retry(self):
        class Broken(Response):
            def readline(self,*args):
                data=super().readline(*args)
                if not data: raise OSError('Disconnected after submission')
                return data
        result,_,bodies,_=self.run_loop([Response([answer('',[call()])]),Broken([{'message':{'content':'Partial'},'prompt_eval_count':5}])])
        self.assertEqual(result['status'],'failed'); self.assertEqual(result['text'],'Partial')
        self.assertEqual(len(bodies),2); self.assertEqual(len(result['research']['sources']),1)
        self.assertEqual(result['metrics']['input_tokens'],17); self.assertFalse(result['metrics']['usage_complete'])
        self.assertEqual(result['research']['attempts'][0]['status'],'failed')

    def test_limits_stop_without_more_tools_or_model_requests(self):
        for limits in (Limits(calls=1),Limits(context_bytes=40)):
            result,_,bodies,backend=self.run_loop([Response([answer('',[call(),call(index=1)])])],limits=limits)
            self.assertEqual(result['research']['status'],'limited'); self.assertEqual(len(bodies),1); self.assertEqual(backend.searches,[])
        result,_,bodies,backend=self.run_loop([Response([answer('',[call()])]),Response([answer('',[call()])])],limits=Limits(rounds=1))
        self.assertEqual(result['research']['status'],'limited'); self.assertEqual(len(backend.searches),1)

    def test_malformed_or_unregistered_batch_does_not_execute_first_valid_call(self):
        for bad in (call('shell',{'command':'anything'},1),call(args='{broken',index=1)):
            result,_,_,backend=self.run_loop([Response([answer('',[call(),bad])])])
            self.assertEqual(result['status'],'failed'); self.assertFalse(backend.searches)

    def test_cancellation_after_tool_does_not_schedule_followup_and_redacts_credentials(self):
        cancel=threading.Event(); backend=Backend(); progress=[]
        def emit(value):
            progress.append(value)
            if any(e['kind']=='tool_completed' for e in value['research']['events']): cancel.set()
        with patch.object(core,'open_request',return_value=Response([answer('web-secret',[call()])])) as transport:
            result=research.run(C,MESSAGES,'web-secret',emit,cancel,backend=backend)
        self.assertEqual(result['research']['status'],'cancelled'); self.assertEqual(transport.call_count,1)
        self.assertNotIn('web-secret',json.dumps(result)); self.assertNotIn('web-secret',json.dumps(progress))
        self.assertEqual(len(result['research']['sources']),1)

    def test_credentials_in_generated_arguments_are_never_transmitted(self):
        result,_,_,backend=self.run_loop([Response([answer('',[call(args={'query':'web-secret'})])])])
        self.assertEqual(result['status'],'failed'); self.assertEqual(backend.searches,[])
        self.assertNotIn('web-secret',json.dumps(result))

    def test_backend_cannot_echo_search_key_into_model_followup(self):
        backend=Backend(); backend.search=lambda **kwargs:[Source('','Evidence','https://example.com/','web-secret','2026-11-08')]
        result,_,bodies,_=self.run_loop([Response([answer('',[call()])]),Response([answer()])],backend)
        self.assertNotIn('web-secret',json.dumps(bodies)); self.assertNotIn('web-secret',json.dumps(result))

    def test_source_ids_remain_unique_and_old_citations_retain_provenance(self):
        older={'id':'S1','title':'Older source','url':'https://example.com/old','excerpt':'Earlier evidence','retrieved_at':'2026-01-01','truncated':True,'backend':'fake'}
        messages=MESSAGES+[{'role':'assistant','text':'Earlier [S1]','research':{'sources':[older]}}]
        responses=[Response([answer('',[call()])]),Response([answer('Compare [S1] with [S2].')])]
        with patch.object(core,'open_request',side_effect=responses):
            result=research.run(C,messages,'key',lambda _:None,threading.Event(),backend=Backend())
        self.assertEqual(result['research']['citations'],['S1','S2'])
        sources={s['id']:s for s in result['research']['sources']}
        self.assertEqual(sources['S1']['retrieved_at'],'2026-01-01')
        self.assertTrue(sources['S1']['retained_from_previous_turn'])
        self.assertEqual(sources['S2']['excerpt'],'Saved evidence')

    def test_only_explicit_native_tool_rejection_changes_capability(self):
        for message,expected in [('HTTP 400: {"error":"test does not support tools"}','unsupported'),
                                 ('HTTP 400: {"error":"invalid parameter"}','configured'),
                                 ('HTTP 401: denied','configured')]:
            with self.subTest(message=message),patch.object(core,'open_request',side_effect=ValueError(message)) as transport:
                result=research.run(C,MESSAGES,'key',lambda _:None,threading.Event(),backend=Backend())
                self.assertEqual(result['research']['capability_state'],expected)
                self.assertEqual(transport.call_count,1)

    def test_model_wire_limit_and_incomplete_stream_never_execute_tools(self):
        for response,limits in [(Response([answer('x'*100)]),Limits(model_bytes=50)),
                                (Response([{'message':{'tool_calls':[call()]}}]),Limits())]:
            result,_,_,backend=self.run_loop([response],limits=limits)
            self.assertEqual(result['status'],'failed'); self.assertFalse(backend.searches)

    def test_failed_tool_records_partial_attempt_and_latency(self):
        backend=Backend(); backend.search=MagicMock(side_effect=ValueError('Web service HTTP 401'))
        result,_,bodies,_=self.run_loop([Response([answer('',[call()])])],backend)
        self.assertEqual(len(bodies),1); self.assertEqual(result['research']['tool_records'][0]['status'],'failed')
        self.assertIn('401',result['research']['tool_records'][0]['error'])
        self.assertGreater(result['metrics']['tool_seconds'],0)
        self.assertEqual(result['metrics']['input_tokens'],12)

    def test_late_model_output_is_rejected_after_timeout(self):
        release=threading.Event(); emitted=[]
        def slow(c,body,runtime,emit,state):
            release.wait(2); emit({'text':'late','thinking':''}); return {},[]
        with patch.object(ollama_tools,'request',side_effect=slow):
            result=research.run(C,MESSAGES,'key',emitted.append,threading.Event(),limits=Limits(request_seconds=.025),backend=Backend())
            size=len(emitted); release.set(); time.sleep(.04)
        self.assertEqual(result['research']['status'],'limited'); self.assertEqual(len(emitted),size)


class TransportContracts(unittest.TestCase):
    def test_hostile_urls_and_mixed_dns_are_blocked(self):
        urls=['file:///etc/passwd','http://user:pass@example.com','http://localhost','http://127.0.0.1',
              'http://[::1]','http://[::ffff:8.8.8.8]','http://[fe80::1%25x]','http://10.1.1.1','http://169.254.169.254',
              'http://example.com:22','http://example.com\\@127.0.0.1','https://example.com/\r\nX:bad']
        for url in urls:
            with self.subTest(url=url),self.assertRaises(AccessError): web.public_url(url)
        with patch.object(socket,'getaddrinfo',return_value=PUBLIC+PRIVATE),self.assertRaises(AccessError):
            web.resolve_public('https://example.com/',Runtime())
        self.assertEqual(web.public_url('https://EXAMPLE.com/path#fragment'),'https://example.com/path')

    def test_pinned_connection_uses_vetted_ip_and_original_tls_hostname(self):
        sock=MagicMock(); context=MagicMock()
        with patch.object(web.socket,'socket',return_value=sock),patch.object(web.ssl,'create_default_context',return_value=context),patch.object(socket,'getaddrinfo') as dns:
            connection=web.PinnedConnection('https://example.com/',PUBLIC,2); connection.connect()
        sock.connect.assert_called_once_with(PUBLIC[0][-1]); dns.assert_not_called()
        context.wrap_socket.assert_called_once_with(sock,server_hostname='example.com')

    def test_redirect_revalidates_and_does_not_forward_authentication(self):
        connection=MagicMock(); response=MagicMock(); response.status=302
        response.getheader.side_effect=lambda name,default=None:'http://127.0.0.1/' if name=='Location' else default
        connection.getresponse.return_value=response
        with patch.object(socket,'getaddrinfo',return_value=PUBLIC),patch.object(web,'PinnedConnection',return_value=connection),self.assertRaises(AccessError):
            web.PublicTransport().request('https://example.com/',Runtime())
        args=connection.request.call_args.kwargs
        self.assertNotIn('Authorization',args['headers']); self.assertNotIn('Cookie',args['headers'])
        self.assertEqual(connection.request.call_count,1)
        response.getheader.side_effect=lambda name,default=None:'https://other.example/' if name=='Location' else default
        with patch.object(socket,'getaddrinfo',side_effect=[PUBLIC,PRIVATE]),patch.object(web,'PinnedConnection',return_value=connection),self.assertRaises(AccessError):
            web.PublicTransport().request('https://example.com/',Runtime())

    def test_redirect_cycles_stop_at_the_configured_bound(self):
        connection=MagicMock(); response=MagicMock(); response.status=302
        response.getheader.side_effect=lambda name,default=None:'/again' if name=='Location' else default
        connection.getresponse.return_value=response
        with patch.object(socket,'getaddrinfo',return_value=PUBLIC),patch.object(web,'PinnedConnection',return_value=connection),self.assertRaises(LimitError):
            web.PublicTransport().request('https://example.com/',Runtime(limits=Limits(redirects=2)))
        self.assertEqual(connection.request.call_count,3)

    def test_response_and_total_byte_limits_and_compression(self):
        connection=MagicMock()
        for headers,data,limits in [({'Content-Encoding':'gzip'},b'',Limits()),({'Content-Length':'100'},b'',Limits(response_bytes=10)),({},b'big payload',Limits(response_bytes=5)),({},b'big payload',Limits(retrieved_bytes=5))]:
            response=io.BytesIO(data)
            response.getheader=lambda name,default=None:headers.get(name,default)
            with self.subTest(headers=headers),self.assertRaises((AccessError,LimitError)):
                web.read_bounded(response,connection,Runtime(limits=limits))

    def test_search_contract_key_isolation_and_readable_fetch(self):
        transport=MagicMock(); transport.request.return_value=('https://ollama.com/api/web_search','application/json',json.dumps({'results':[{'title':'Example','url':'https://example.com','content':'Evidence'*1000}]}).encode())
        service=web.OllamaWeb('only-web-key',transport); runtime=Runtime()
        with patch.object(socket,'getaddrinfo',return_value=PUBLIC): sources=service.search('necessary terms',runtime)
        request=transport.request.call_args
        self.assertEqual(json.loads(request.kwargs['body']),{'query':'necessary terms','max_results':5})
        self.assertEqual(request.kwargs['headers']['Authorization'],'Bearer only-web-key'); self.assertFalse(request.kwargs['redirects'])
        self.assertTrue(sources[0].truncated)
        transport.request.return_value=('https://example.com/','text/html',b'<title>Title</title><script>evil()</script><p>Read this</p>')
        sources=service.fetch('https://example.com/',runtime)
        self.assertNotIn('headers',transport.request.call_args.kwargs)
        self.assertNotIn('evil',sources[0].excerpt); self.assertEqual(sources[0].title,'Title')

    def test_service_redirect_content_type_and_malformed_json_errors(self):
        connection=MagicMock(); r=MagicMock(); connection.getresponse.return_value=r
        with patch.object(socket,'getaddrinfo',return_value=PUBLIC),patch.object(web,'PinnedConnection',return_value=connection):
            r.status=302
            with self.assertRaises(AccessError): web.PublicTransport().request('https://ollama.com/',Runtime(),body=b'{}',redirects=False)
            r.status=200; r.getheader.return_value='application/pdf'
            with self.assertRaises(AccessError): web.PublicTransport().request('https://example.com/',Runtime())
        transport=MagicMock(); transport.request.return_value=('','application/json',b'{broken')
        with self.assertRaisesRegex(ValueError,'Malformed'): web.OllamaWeb('key',transport).search('x',Runtime())
        with self.assertRaisesRegex(ValueError,'credential'): web.OllamaWeb('key\nbad',transport)


if __name__=='__main__': unittest.main()

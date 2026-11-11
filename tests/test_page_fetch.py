"""Provider page fallback: offline fixtures and mock model continuations only."""
import io
import json
import ssl
import tempfile
import threading
import unittest
from unittest.mock import MagicMock,patch
from agentnik import core,web,research
from agentnik.page_fetch import PageFetcher,provider_page
from agentnik.tools import Runtime,AccessError,Source
from test_research import PUBLIC,PRIVATE,C,MESSAGES,Response,answer,call


class PageRetrieval(unittest.TestCase):
    def test_direct_success_does_not_use_provider(self):
        direct=MagicMock();direct.fetch.return_value=['direct']
        with patch('agentnik.page_fetch.provider_page') as provider:
            self.assertEqual(PageFetcher([],direct).fetch('https://example.com/',Runtime()),['direct']);provider.assert_not_called()

    def test_filter_detection_distinguishes_docs_and_site_denial(self):
        block=b'<title>Web Site Blocked</title><p>Zscaler Internet Security</p>'
        self.assertTrue(web.filter_page(block));self.assertFalse(web.filter_page(b'<title>Zscaler API docs</title>How to handle access denied'))
        transport=MagicMock();transport.request.return_value=('https://example.com/','text/html',block)
        with self.assertRaises(web.FilteredPageError):web.PublicWeb(transport).fetch('https://example.com/',Runtime())
        connection=MagicMock();r=MagicMock();r.status=403;r.getheader.side_effect=lambda name,default=None:'Zscaler' if name=='Server' else default
        connection.getresponse.return_value=r
        with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch.object(web,'PinnedConnection',return_value=connection):
            with self.assertRaises(web.FilteredPageError):web.PublicTransport().request('https://example.com/',Runtime())

    def test_direct_failure_uses_only_configured_capable_provider_and_records_disclosure(self):
        for error in (web.FilteredPageError('filtered'),ssl.SSLCertVerificationError('interception'),ConnectionResetError(),ConnectionRefusedError(),core.EndpointError(404,'{}'),core.EndpointError(503,'{}')):
            direct=MagicMock();direct.fetch.side_effect=error;runtime=Runtime();events=[];runtime.notify=lambda *e:events.append(e)
            specs=[{'id':'free','kind':'firecrawl-keyless','key':''},{'id':'search','kind':'brave','key':'key'},{'id':'configured','kind':'exa','name':'Exa','key':'key'}]
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch('agentnik.page_fetch.provider_page',return_value=['provider']) as provider:
                self.assertEqual(PageFetcher(specs,direct).fetch('https://example.com/',runtime),['provider'])
            self.assertEqual(provider.call_args.args[0]['kind'],'exa');self.assertTrue(any('sending the public page URL' in e[1] for e in events))

    def test_no_automatic_or_configured_keyless_page_fallback(self):
        for specs in ([],[{'id':'free','kind':'firecrawl-keyless','key':''}],[{'id':'empty','kind':'exa','key':''}]):
            direct=MagicMock();direct.fetch.side_effect=web.FilteredPageError('filtered')
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch('agentnik.page_fetch.provider_page') as provider:
                with self.assertRaises(web.FilteredPageError):PageFetcher(specs,direct).fetch('https://example.com/',Runtime())
                provider.assert_not_called()

    def test_direct_public_tls_is_relaxed_and_provider_tls_remains_verified(self):
        self.assertFalse(web.PublicWeb().transport.verify_tls)
        for adapter in (web.PublicTransport(),web.GoogleWeb().transport,web.OllamaWeb('key').transport,web.FirecrawlWeb('key').transport,web.FirecrawlKeylessWeb().transport):
            self.assertTrue(adapter.verify_tls)
        sock=MagicMock();wrapped=MagicMock();observed=[]
        def wrap(context,socket,server_hostname=None):
            observed.append((context.verify_mode,context.check_hostname,server_hostname));return wrapped
        with patch.object(web.socket,'socket',return_value=sock),patch.object(ssl.SSLContext,'wrap_socket',wrap):
            web.PinnedConnection('https://example.com/',PUBLIC,5,verify_tls=False).connect()
            web.PinnedConnection('https://example.com/',PUBLIC,5).connect()
        self.assertEqual(observed,[(ssl.CERT_NONE,False,'example.com'),(ssl.CERT_REQUIRED,True,'example.com')])

    def test_policy_private_addresses_and_uncertain_failures_never_use_provider(self):
        for error in (AccessError('Private redirect'),core.EndpointError(403,'{}'),TimeoutError()):
            direct=MagicMock();direct.fetch.side_effect=error
            with patch('agentnik.page_fetch.provider_page') as provider:
                with self.assertRaises(type(error)):PageFetcher([],direct).fetch('https://example.com/',Runtime())
                provider.assert_not_called()
        direct=MagicMock();direct.fetch.side_effect=web.FilteredPageError('filtered')
        with patch('agentnik.page_fetch.provider_page') as provider:
            with self.assertRaises(web.FilteredPageError):PageFetcher([],direct,allow_external=False).fetch('https://example.com/',Runtime())
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC+PRIVATE):
                with self.assertRaises(AccessError):PageFetcher([],direct).fetch('https://example.com/',Runtime())
            provider.assert_not_called()

    def test_provider_request_contracts_and_source_provenance(self):
        fixtures=[('firecrawl',{'success':True,'data':{'markdown':'# Docs','metadata':{'title':'Docs','url':'https://example.com/','statusCode':200}}},'/v2/scrape'),
                  ('exa',{'results':[{'url':'https://example.com/','title':'Docs','text':'# Docs'}]},'/contents'),
                  ('parallel',{'results':[{'url':'https://example.com/','title':'Docs','excerpts':['# Docs']}]},'/v1/extract'),
                  ('ollama',{'title':'Docs','content':'# Docs'},'/api/web_fetch')]
        for kind,payload,path in fixtures:
            key='search-fixture';spec={'id':'profile','kind':kind,'key':key}
            transport=MagicMock();transport.request.return_value=('','application/json',json.dumps(payload).encode())
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):sources=provider_page(spec,'https://example.com/',Runtime(),transport)
            request=transport.request.call_args;self.assertTrue(request.args[0].endswith(path));self.assertFalse(request.kwargs['redirects'])
            body=json.loads(request.kwargs['body']);self.assertNotIn('search-fixture',json.dumps(body));self.assertEqual(sources[0].excerpt,'# Docs');self.assertEqual(sources[0].backend,'profile-page-api')
            self.assertIn('search-fixture',str(request.kwargs['headers']))

    def test_provider_private_final_urls_and_restricted_results_are_rejected(self):
        for metadata in ({'url':'http://127.0.0.1/'},{'statusCode':403}):
            transport=MagicMock();transport.request.return_value=('','application/json',json.dumps({'success':True,'data':{'markdown':'text','metadata':metadata}}).encode())
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):
                with self.assertRaises(AccessError):provider_page({'id':'configured','kind':'firecrawl','key':'fixture'},'https://example.com/',Runtime(),transport)

    def test_chat_and_code_receive_provider_page_without_inference_replay(self):
        config={};research.set_capability(config,C,'configured','fixture');source=[Source('','Docs','https://example.com/','Provider page','now',backend='configured-page-api')]
        specs=[{'id':'configured','kind':'firecrawl','name':'Firecrawl','key':'fixture-key'}]
        def failed(*args,**kwargs):raise web.FilteredPageError('filtered')
        with patch.object(core,'open_request',side_effect=[Response([answer('',[call('web_fetch',{'url':'https://example.com/'})])]),Response([answer()])]) as model,patch.object(web.PublicWeb,'fetch',side_effect=failed),patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch('agentnik.page_fetch.provider_page',return_value=source):
            result=research.run(C,MESSAGES,'',lambda _:None,threading.Event(),config=config,policy='Agentnik only',backends=specs)
        self.assertEqual(result['status'],'ok');self.assertEqual(model.call_count,2)
        from agentnik.code_agent import CodingRun
        from test_code_agent import C as gateway,call as code_call
        from test_compat_tools import chat
        from test_routing import Wire
        with tempfile.TemporaryDirectory() as directory:
            events=[]
            with patch.object(core,'open_request',side_effect=[Wire(chat(calls=[code_call('web_fetch',{'url':'https://example.com/'})],finish='tool_calls'),False),Wire(chat('Read docs'),False)]) as model,patch.object(web.PublicWeb,'fetch',side_effect=failed),patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch('agentnik.page_fetch.provider_page',return_value=source):
                CodingRun(dict(gateway,stream=False),directory,'Research',web_enabled=True,search_provider='managed',web_backends=specs).run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertEqual(model.call_count,2);self.assertTrue(any(e['kind']=='source' for e in events))

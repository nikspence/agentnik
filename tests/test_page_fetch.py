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

    def test_filtered_or_tls_failure_uses_default_keyless_and_records_disclosure(self):
        for error in (web.FilteredPageError('filtered'),ssl.SSLCertVerificationError('interception'),ConnectionResetError()):
            direct=MagicMock();direct.fetch.side_effect=error;runtime=Runtime();events=[];runtime.notify=lambda *e:events.append(e)
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch('agentnik.page_fetch.provider_page',return_value=['provider']) as provider:
                self.assertEqual(PageFetcher([],direct).fetch('https://example.com/',runtime),['provider'])
            self.assertEqual(provider.call_args.args[0]['kind'],'firecrawl-keyless');self.assertTrue(any('sending the public page URL' in e[1] for e in events))

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
                  ('firecrawl-keyless',{'success':True,'data':{'markdown':'# Docs'}},'/v2/scrape'),
                  ('exa',{'results':[{'url':'https://example.com/','title':'Docs','text':'# Docs'}]},'/contents'),
                  ('parallel',{'results':[{'url':'https://example.com/','title':'Docs','excerpts':['# Docs']}]},'/v1/extract'),
                  ('ollama',{'title':'Docs','content':'# Docs'},'/api/web_fetch')]
        for kind,payload,path in fixtures:
            key='' if kind=='firecrawl-keyless' else 'search-fixture';spec={'id':'profile','kind':kind,'key':key}
            transport=MagicMock();transport.request.return_value=('','application/json',json.dumps(payload).encode())
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):sources=provider_page(spec,'https://example.com/',Runtime(),transport)
            request=transport.request.call_args;self.assertTrue(request.args[0].endswith(path));self.assertFalse(request.kwargs['redirects'])
            body=json.loads(request.kwargs['body']);self.assertNotIn('search-fixture',json.dumps(body));self.assertEqual(sources[0].excerpt,'# Docs');self.assertEqual(sources[0].backend,'profile-page-api')
            if kind=='firecrawl-keyless':self.assertNotIn('Authorization',request.kwargs['headers'])
            else:self.assertIn('search-fixture',str(request.kwargs['headers']))

    def test_provider_private_final_urls_and_restricted_results_are_rejected(self):
        for metadata in ({'url':'http://127.0.0.1/'},{'statusCode':403}):
            transport=MagicMock();transport.request.return_value=('','application/json',json.dumps({'success':True,'data':{'markdown':'text','metadata':metadata}}).encode())
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):
                with self.assertRaises(AccessError):provider_page({'id':'free','kind':'firecrawl-keyless','key':''},'https://example.com/',Runtime(),transport)

    def test_chat_and_code_receive_provider_page_without_inference_replay(self):
        config={};research.set_capability(config,C,'configured','fixture');source=[Source('','Docs','https://example.com/','Provider page','now',backend='free-page-api')]
        def failed(*args,**kwargs):raise web.FilteredPageError('filtered')
        with patch.object(core,'open_request',side_effect=[Response([answer('',[call('web_fetch',{'url':'https://example.com/'})])]),Response([answer()])]) as model,patch.object(web.PublicWeb,'fetch',side_effect=failed),patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch('agentnik.page_fetch.provider_page',return_value=source):
            result=research.run(C,MESSAGES,'',lambda _:None,threading.Event(),config=config,policy='Agentnik only',backends=[])
        self.assertEqual(result['status'],'ok');self.assertEqual(model.call_count,2)
        from agentnik.code_agent import CodingRun
        from test_code_agent import C as gateway,call as code_call
        from test_compat_tools import chat
        from test_routing import Wire
        with tempfile.TemporaryDirectory() as directory:
            events=[]
            with patch.object(core,'open_request',side_effect=[Wire(chat(calls=[code_call('web_fetch',{'url':'https://example.com/'})],finish='tool_calls'),False),Wire(chat('Read docs'),False)]) as model,patch.object(web.PublicWeb,'fetch',side_effect=failed),patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch('agentnik.page_fetch.provider_page',return_value=source):
                CodingRun(dict(gateway,stream=False),directory,'Research',web_enabled=True,search_provider='managed').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertEqual(model.call_count,2);self.assertTrue(any(e['kind']=='source' for e in events))

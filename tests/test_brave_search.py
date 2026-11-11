"""Brave adapter and provider profiles: offline fixtures, never live API calls."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from urllib.parse import urlsplit,parse_qs
from agentnik import web,core,routing,research
from agentnik.storage import Store
from agentnik.tools import Runtime,Limits,AccessError,ResearchError
from test_research import PUBLIC


class BraveSearch(unittest.TestCase):
    def test_request_contract_and_bounded_plain_sources(self):
        transport=MagicMock();transport.request.return_value=('', 'application/json',json.dumps({'web':{'results':[{'title':'Docs','url':'https://example.com/docs','description':'<b>API</b> &amp; examples'},{'title':'More','url':'https://example.com/more','description':None}]}}).encode())
        with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):
            sources=web.BraveWeb('test-search-key',transport).search('Qt signals',Runtime(limits=Limits(results=2)))
        args=transport.request.call_args
        self.assertEqual(urlsplit(args.args[0]).netloc,'api.search.brave.com')
        self.assertEqual(parse_qs(urlsplit(args.args[0]).query)['count'],['2'])
        self.assertEqual(args.kwargs['headers']['X-Subscription-Token'],'test-search-key')
        self.assertFalse(args.kwargs['redirects']);self.assertNotIn('body',args.kwargs)
        self.assertNotIn('test-search-key',args.args[0]);self.assertEqual(sources[0].excerpt,'API & examples')
        self.assertEqual(sources[1].excerpt,'');self.assertEqual(sources[0].backend,'brave-search')

    def test_malformed_empty_private_and_query_validation(self):
        transport=MagicMock()
        for payload in (b'not json',b'[]',b'{}',b'{"web":[]}',b'{"web":{"results":[{"url":"https://example.com"}]}}'):
            transport.request.return_value=('','application/json',payload)
            with self.assertRaises(ResearchError):web.BraveWeb('test-key',transport).search('query',Runtime())
        for payload in (b'{"query":{}}',b'{"web":{"results":[]}}'):
            transport.request.return_value=('','application/json',payload)
            self.assertEqual(web.BraveWeb('test-key',transport).search('query',Runtime()),[])
        transport.request.return_value=('','application/json',b'{"web":{"results":[{"title":"Private","url":"http://127.0.0.1/","description":"secret"}]}}')
        self.assertEqual(web.BraveWeb('test-key',transport).search('query',Runtime()),[])
        for query in ('','x'*601,'word '*76,'test-key'):
            with self.assertRaises(ResearchError):web.BraveWeb('test-key',transport).search(query,Runtime())
        with self.assertRaises(ResearchError):web.BraveWeb('bad\nkey')

    def test_brave_skips_only_nonpublic_results_and_keeps_public_hits(self):
        transport=MagicMock();payload={'web':{'results':[{'title':'Private','url':'http://127.0.0.1/'},{'title':'Public','url':'https://example.com/docs','description':'Documentation'}]}}
        transport.request.return_value=('','application/json',json.dumps(payload).encode());events=[];runtime=Runtime();runtime.notify=lambda kind,detail:events.append((kind,detail))
        with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):results=web.BraveWeb('test-key',transport).search('query',runtime)
        self.assertEqual([item.title for item in results],['Public']);self.assertEqual(events[0][0],'result_filtered');self.assertNotIn('127.0.0.1',str(events))
        payload['web']['results'][0]['description']='test-key';transport.request.return_value=('','application/json',json.dumps(payload).encode())
        with self.assertRaises(AccessError):web.BraveWeb('test-key',transport).search('query',runtime)

    def test_access_diagnostics_include_http_status_without_credentials(self):
        spec={'id':'brave','kind':'brave','name':'Brave Search','key':'private-key'};events=[];runtime=Runtime();runtime.notify=lambda kind,detail:events.append((kind,detail))
        with patch.object(web,'BraveWeb') as provider:
            provider.return_value.search.side_effect=core.EndpointError(403,'private-key')
            with self.assertRaises(core.EndpointError):web.OrderedSearch([spec]).search('query',runtime)
        self.assertTrue(any('HTTP 403' in detail for _,detail in events));self.assertNotIn('private-key',str(events));provider.assert_called_once()

    def test_json_get_exception_is_limited_to_fixed_brave_service(self):
        connection=MagicMock()
        def response():
            r=io.BytesIO(b'{"web":{"results":[]}}');r.status=200
            r.getheader=lambda name,default=None:'application/json' if name=='Content-Type' else default
            return r
        with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC),patch.object(web,'PinnedConnection',return_value=connection):
            for url,redirects in [('https://api.search.brave.com/res/v1/web/search?q=Qt',False),('https://example.com/res/v1/web/search',False),('https://api.search.brave.com/other',False),('https://api.search.brave.com/res/v1/web/search',True)]:
                connection.getresponse.return_value=response()
                if url.endswith('q=Qt'):self.assertEqual(web.PublicTransport().request(url,Runtime(),redirects=redirects)[1],'application/json')
                else:
                    with self.assertRaises(AccessError):web.PublicTransport().request(url,Runtime(),redirects=redirects)

    def test_eligible_rate_limit_fallback_and_access_stop(self):
        specs=[{'id':'a','kind':'brave','name':'Primary','key':'a-key'},{'id':'b','kind':'brave','name':'Secondary','key':'b-key'}]
        for outcome in (core.EndpointError(429,'{}',retry_after='0'),AccessError('blocked'),[]):
            first=MagicMock();second=MagicMock();second.search.return_value=[]
            if isinstance(outcome,Exception):first.search.side_effect=outcome
            else:first.search.return_value=outcome
            with patch.object(web,'BraveWeb',side_effect=[first,second]) as factory:
                if isinstance(outcome,AccessError):
                    with self.assertRaises(AccessError):web.OrderedSearch(specs).search('query',Runtime())
                else:self.assertEqual(web.OrderedSearch(specs).search('query',Runtime()),[])
                self.assertEqual(factory.call_count,2 if isinstance(outcome,core.EndpointError) else 1)

    def test_profiles_preserve_provider_and_use_independent_credential_store(self):
        secrets={};keyring=MagicMock()
        keyring.set_password.side_effect=lambda service,ident,key:secrets.__setitem__((service,ident),key)
        keyring.get_password.side_effect=lambda service,ident:secrets.get((service,ident))
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'keyring':keyring}),patch.dict(os.environ,{'BRAVE_SEARCH_API_KEY':'env-brave-key','OLLAMA_WEB_API_KEY':''}):
            store=Store(directory)
            try:
                self.assertEqual(store.web_backend_specs()[0]['kind'],'brave')
                store.save_web_key('brave-secret',ident='primary',name='Primary',kind='brave')
                ident=store.config['web_backends'][0]['credential_id']
                self.assertEqual(secrets[('Agentnik Web',ident)],'brave-secret')
                self.assertNotIn('brave-secret',store.config_path.read_text())
                store.save_web_key('replacement-secret',ident='primary')
                self.assertEqual(store.config['web_backends'][0]['kind'],'brave')
                store.save_web_key('environment-override',ident='brave-search',plaintext=True)
                self.assertEqual(store.config['web_backends'][1]['kind'],'brave')
                self.assertEqual(len(store.web_backend_specs()),2)
                c={'url':'https://gateway.example/v1','protocol':'chat','model':'model'};research.set_capability(store.config,c,'configured','test')
                self.assertEqual(routing.eligible('managed',c,store.config,store.web_backend_specs(),'public_fetch'),'')
                self.assertTrue(routing.eligible('managed',c,store.config,store.web_backend_specs(),'strict_public'))
            finally:store.db.close()
            reopened=Store(directory)
            try:self.assertEqual(reopened.config['web_backends'][0]['kind'],'brave')
            finally:reopened.db.close()


class AdditionalSearchProviders(unittest.TestCase):
    def test_langsearch_and_firecrawl_request_shapes_and_results(self):
        fixtures=[(web.LangSearchWeb,'api.langsearch.com',{'code':200,'data':{'webPages':{'value':[{'name':'Docs','url':'https://example.com/','snippet':'An <b>API</b> guide'}]}}}),
                  (web.FirecrawlWeb,'api.firecrawl.dev',{'success':True,'data':{'web':[{'title':'Docs','url':'https://example.com/','description':'An API guide'}]}})]
        for adapter,host,payload in fixtures:
            with self.subTest(provider=host):
                transport=MagicMock();transport.request.return_value=('','application/json',json.dumps(payload).encode())
                with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):sources=adapter('fixture-key',transport).search('API docs',Runtime(limits=Limits(results=2)))
                args=transport.request.call_args;body=json.loads(args.kwargs['body'])
                self.assertEqual(urlsplit(args.args[0]).hostname,host);self.assertEqual(args.kwargs['headers']['Authorization'],'Bearer fixture-key');self.assertFalse(args.kwargs['redirects'])
                self.assertEqual(sources[0].excerpt,'An API guide')
                if adapter is web.LangSearchWeb:
                    self.assertEqual(body,{'query':'API docs','count':2,'contents':{'text':False}})
                else:
                    self.assertEqual(body,{'query':'API docs','limit':2,'sources':[{'type':'web'}]});self.assertNotIn('scrapeOptions',body)

    def test_provider_errors_and_empty_results(self):
        for adapter,empty in [(web.LangSearchWeb,{'code':200,'data':{'webPages':{'value':[]}}}),(web.FirecrawlWeb,{'success':True,'data':{'web':[]}})]:
            transport=MagicMock();transport.request.return_value=('','application/json',json.dumps(empty).encode())
            self.assertEqual(adapter('fixture',transport).search('query',Runtime()),[])
            for raw in (b'[]',b'{"success":false}',b'{"code":429}',b'{"success":true,"data":{"web":{}}}',b'not JSON'):
                transport.request.return_value=('','application/json',raw)
                with self.assertRaises(ResearchError):adapter('fixture',transport).search('query',Runtime())

    def test_all_environment_profiles_are_bounded_and_not_persisted(self):
        variables={'BRAVE_SEARCH_API_KEY':'brave-fixture','LANGSEARCH_API_KEY':'lang-fixture','FIRECRAWL_API_KEY':'fire-fixture','OLLAMA_WEB_API_KEY':'ollama-fixture'}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,variables):
            store=Store(directory)
            try:
                self.assertEqual([e['kind'] for e in store.web_backend_specs()],['brave','langsearch','firecrawl','ollama'])
                self.assertNotIn('web_backends',store.config)
                for n in range(4):store.save_web_key('fixture-'+str(n),plaintext=True,ident='saved-'+str(n),kind='langsearch')
                self.assertEqual(len(store.web_backend_specs()),5)
                self.assertEqual(store.web_backend_specs()[-1]['kind'],'brave')
            finally:store.db.close()

    def test_search_profiles_feed_chat_and_code_without_model_credentials(self):
        import threading
        from test_research import C,MESSAGES,Response,answer,call as native_call,Backend
        config={};research.set_capability(config,C,'configured','fixture')
        specs=[{'id':'brave-profile','kind':'brave','name':'Brave','key':'search-secret'}]
        replies=[Response([answer('',[native_call()])]),Response([answer()])]
        with patch.object(core,'open_request',side_effect=replies) as model,patch.object(web,'BraveWeb',return_value=Backend()) as provider:
            result=research.run(C,MESSAGES,'',lambda _:None,threading.Event(),config=config,policy='Agentnik only',backends=specs)
        self.assertEqual(result['status'],'ok');self.assertEqual(provider.call_args.args,('search-secret',))
        self.assertNotIn('search-secret',json.dumps(result));self.assertNotIn('search-secret',json.dumps([call.args[2] for call in model.call_args_list]))
        from test_code_agent import C as gateway,call
        from test_compat_tools import chat
        from test_routing import Wire
        from agentnik.code_agent import CodingRun
        with tempfile.TemporaryDirectory() as directory:
            events=[];replies=[Wire(chat(calls=[call('web_search',{'query':'API'})],finish='tool_calls'),False),Wire(chat('Done [S1]'),False)]
            with patch.object(core,'open_request',side_effect=replies),patch.object(web,'BraveWeb',return_value=Backend()),patch('agentnik.code_agent.GoogleWeb') as google:
                CodingRun(dict(gateway,stream=False),directory,'Research',web_backends=specs,web_enabled=True,search_provider='managed').run(events.append)
                google.assert_not_called()
            self.assertEqual(events[-1]['status'],'completed');self.assertTrue(any(e['kind']=='source' for e in events))
            self.assertNotIn('search-secret',json.dumps(events))

    def test_profile_editor_exposes_provider_choices_and_saves_selected_kind(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog,QComboBox,QLineEdit
        from agentnik.research_ui import SearchBackends
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'keyring':MagicMock()}):
            store=Store(directory);manager=SearchBackends(None,store)
            def accept(dialog):
                provider=dialog.findChild(QComboBox,'searchProvider')
                self.assertEqual([provider.itemData(i) for i in range(provider.count())],['brave','langsearch','firecrawl','firecrawl-keyless','exa','parallel','ollama'])
                provider.setCurrentIndex(provider.findData('firecrawl'))
                dialog.findChild(QLineEdit,'searchKey').setText('firecrawl-fixture')
                return QDialog.DialogCode.Accepted
            try:
                with patch.object(QDialog,'exec',accept):manager.edit(True)
                self.assertEqual(store.config['web_backends'][0]['kind'],'firecrawl');self.assertEqual(store.config['web_backends'][0]['name'],'Firecrawl')
            finally:manager.close();app.processEvents();store.db.close()

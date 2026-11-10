"""Exa and Parallel: bounded requests and model-independent research, offline only."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock,patch
from agentnik import core,research,web
from agentnik.storage import Store
from agentnik.tools import Runtime,Limits,ResearchError,AccessError
from test_research import PUBLIC,Backend,C,MESSAGES,Response,answer,call

PROVIDERS=[('exa',web.ExaWeb,'highlights'),('parallel',web.ParallelWeb,'excerpts')]


class ExcerptProviders(unittest.TestCase):
    def test_requests_use_explicit_modes_and_only_query_options(self):
        for kind,adapter,field in PROVIDERS:
            with self.subTest(provider=kind):
                transport=MagicMock();payload={'results':[{'title':'Docs','url':'https://example.com/docs',field:['Use <T> with API','Another passage']}]}
                transport.request.return_value=('','application/json',json.dumps(payload).encode())
                with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):sources=adapter('fixture-key',transport).search('API documentation',Runtime(limits=Limits(results=2,context_bytes=5000)))
                request=transport.request.call_args;body=json.loads(request.kwargs['body'])
                self.assertEqual(request.args[0],adapter.service_url);self.assertFalse(request.kwargs['redirects'])
                self.assertEqual(request.kwargs['headers']['x-api-key'],'fixture-key')
                if kind=='exa':self.assertEqual(body,{'query':'API documentation','type':'auto','numResults':2,'contents':{'highlights':True}})
                else:self.assertEqual(body,{'search_queries':['API documentation'],'mode':'basic','max_chars_total':5000})
                self.assertEqual(sources[0].excerpt,'Use <T> with API\nAnother passage');self.assertEqual(sources[0].backend,kind+'-search')
                self.assertNotIn('fixture-key',request.args[0]);self.assertNotIn('fixture-key',json.dumps(body))

    def test_excerpts_and_result_count_are_bounded(self):
        for kind,adapter,field in PROVIDERS:
            transport=MagicMock();payload={'results':[{'title':'Docs','url':'https://example.com',field:['가'*4000]}]*3}
            transport.request.return_value=('','application/json',json.dumps(payload).encode())
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):sources=adapter('fixture-key',transport).search('query',Runtime(limits=Limits(results=1)))
            self.assertEqual(len(sources),1);self.assertLessEqual(len(sources[0].excerpt.encode()),3000);self.assertTrue(sources[0].truncated)

    def test_empty_metadata_only_and_malformed_responses(self):
        for kind,adapter,field in PROVIDERS:
            transport=MagicMock()
            for raw in (b'not JSON',b'[]',b'{}',b'{"results":{}}',b'{"error":"rejected","results":[]}',json.dumps({'results':[{'title':'Docs','url':'https://example.com',field:[42]}]}).encode()):
                transport.request.return_value=('','application/json',raw)
                with self.assertRaises(ResearchError):adapter('fixture-key',transport).search('query',Runtime())
            transport.request.return_value=('','application/json',b'{"results":[]}')
            self.assertEqual(adapter('fixture-key',transport).search('query',Runtime()),[])
            transport.request.return_value=('','application/json',b'{"results":[{"title":"Docs","url":"https://example.com"}]}')
            with patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):self.assertEqual(adapter('fixture-key',transport).search('query',Runtime())[0].excerpt,'')

    def test_private_secret_and_cancelled_requests_are_blocked(self):
        for kind,adapter,field in PROVIDERS:
            transport=MagicMock()
            for url in ('http://127.0.0.1/','https://example.com/?secret=fixture-key'):
                transport.request.return_value=('','application/json',json.dumps({'results':[{'title':'Docs','url':url,field:['text']}]}).encode())
                with self.assertRaises(AccessError):adapter('fixture-key',transport).search('query',Runtime())
            transport.reset_mock();cancel=threading.Event();cancel.set()
            with self.assertRaises(InterruptedError):adapter('fixture-key',transport).search('query',Runtime(cancel))
            transport.request.assert_not_called()
            for query in ('','x'*1001,'fixture-key'):
                with self.assertRaises(ResearchError):adapter('fixture-key',transport).search(query,Runtime())
            transport.request.assert_not_called()

    def test_cross_provider_fallback_requires_definite_eligible_rejection(self):
        specs=[{'id':'exa','kind':'exa','key':'exa-fixture'},{'id':'parallel','kind':'parallel','key':'parallel-fixture'}]
        for error,expected in [(core.EndpointError(401,'{}'),2),(core.EndpointError(403,'{}'),1),(TimeoutError(),1)]:
            first=MagicMock();first.search.side_effect=error;second=MagicMock();second.search.return_value=[]
            with patch.object(web,'ExaWeb',return_value=first),patch.object(web,'ParallelWeb',return_value=second):
                service=web.OrderedSearch(specs)
                if expected==2:self.assertEqual(service.search('query',Runtime()),[])
                else:
                    with self.assertRaises(type(error)):service.search('query',Runtime())
                self.assertEqual(len(service.attempts),expected)

    def test_chat_and_code_use_both_providers_without_leaking_keys(self):
        from agentnik.code_agent import CodingRun
        from test_code_agent import C as gateway,call as code_call
        from test_compat_tools import chat
        from test_routing import Wire
        for kind,adapter,_ in PROVIDERS:
            with self.subTest(provider=kind):
                config={};research.set_capability(config,C,'configured','fixture')
                specs=[{'id':kind,'kind':kind,'name':kind,'key':kind+'-secret'}]
                replies=[Response([answer('',[call()])]),Response([answer()])]
                with patch.object(core,'open_request',side_effect=replies) as model,patch.object(web,adapter.__name__,return_value=Backend()):
                    result=research.run(C,MESSAGES,'',lambda _:None,threading.Event(),config=config,policy='Agentnik only',backends=specs)
                self.assertEqual(result['status'],'ok');self.assertNotIn(kind+'-secret',json.dumps(result))
                self.assertNotIn(kind+'-secret',json.dumps([request.args[2] for request in model.call_args_list]))
                with tempfile.TemporaryDirectory() as directory:
                    events=[];replies=[Wire(chat(calls=[code_call('web_search',{'query':'API'})],finish='tool_calls'),False),Wire(chat('Done [S1]'),False)]
                    with patch.object(core,'open_request',side_effect=replies),patch.object(web,adapter.__name__,return_value=Backend()),patch('agentnik.code_agent.GoogleWeb') as google:
                        CodingRun(dict(gateway,stream=False),directory,'Research',web_backends=specs,search_provider='managed').run(events.append)
                        google.assert_not_called()
                    self.assertEqual(events[-1]['status'],'completed');self.assertNotIn(kind+'-secret',json.dumps(events))

    def test_profiles_environment_overrides_and_replacement_preserve_kind(self):
        from agentnik.search_providers import SEARCH_PROVIDERS
        variables={variable:'' for _,variable,_ in SEARCH_PROVIDERS.values() if variable};variables.update(EXA_API_KEY='exa-environment',PARALLEL_API_KEY='parallel-environment')
        keyring=MagicMock();secrets={}
        keyring.set_password.side_effect=lambda service,ident,key:secrets.__setitem__((service,ident),key)
        keyring.get_password.side_effect=lambda service,ident:secrets.get((service,ident))
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,variables),patch.dict('sys.modules',{'keyring':keyring}):
            store=Store(directory)
            try:
                self.assertEqual([s['kind'] for s in store.web_backend_specs()],['exa','parallel'])
                for kind,_,_ in PROVIDERS:
                    store.save_web_key(kind+'-key',ident=kind+'-search')
                    store.save_web_key(kind+'-replacement',ident=kind+'-search')
                self.assertEqual([s['kind'] for s in store.web_backend_specs()],['exa','parallel'])
                self.assertNotIn('exa-replacement',store.config_path.read_text())
                self.assertEqual(store.web_key('parallel-search'),'parallel-replacement')
            finally:store.db.close()
            store=Store(directory)
            try:self.assertEqual([s['kind'] for s in store.web_backend_specs()],['exa','parallel'])
            finally:store.db.close()

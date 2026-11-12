"""Keyless Firecrawl and automatic fallback; fixtures only, no live web calls."""
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock,patch
from agentnik import core,web,research,routing
from agentnik.storage import Store
from agentnik.search_providers import search_chain
from agentnik.tools import Runtime,AccessError
from test_research import PUBLIC,Backend,C,MESSAGES,Response,answer,call


class KeylessFirecrawl(unittest.TestCase):
    def test_keyless_request_has_no_authorization_or_environment_key(self):
        transport=MagicMock();transport.request.return_value=('','application/json',b'{"success":true,"data":{"web":[{"title":"Docs","url":"https://example.com/","description":"Evidence"}]}}')
        with patch.dict(os.environ,{'FIRECRAWL_API_KEY':'must-not-use'}),patch.object(web.socket,'getaddrinfo',return_value=PUBLIC):
            result=web.FirecrawlKeylessWeb(transport=transport).search('API docs',Runtime())
        self.assertEqual(len(result),1);request=transport.request.call_args
        self.assertNotIn('Authorization',request.kwargs['headers']);self.assertNotIn('must-not-use',str(request))
        self.assertFalse(request.kwargs['redirects'])
        self.assertNotIn('scrapeOptions',json.loads(request.kwargs['body']))
        with self.assertRaises(ValueError):web.FirecrawlWeb('')
        with self.assertRaises(ValueError):web.FirecrawlKeylessWeb('key-not-allowed')

    def test_default_and_configured_chain_order_and_deduplication(self):
        self.assertEqual([s['kind'] for s in search_chain([])],['firecrawl-keyless','google'])
        configured=[{'id':'primary','kind':'brave','key':'fixture'}]
        self.assertEqual([s['kind'] for s in search_chain(configured)],['brave','firecrawl-keyless','google'])
        self.assertEqual(len(configured),1)
        explicit=[{'id':'chosen','kind':'firecrawl-keyless','key':''},*configured]
        chain=search_chain(explicit);self.assertEqual([s['kind'] for s in chain],['firecrawl-keyless','brave','google'])
        self.assertEqual(search_chain(chain),chain)

    def test_quota_rejection_uses_google_and_does_not_retry_keyless(self):
        keyless=MagicMock();keyless.search.side_effect=core.EndpointError(429,'{}',retry_after='86400')
        google=Backend();runtime=Runtime();events=[];runtime.notify=lambda *e:events.append(e)
        with patch.object(web,'FirecrawlKeylessWeb',return_value=keyless),patch.object(web,'GoogleWeb',return_value=google):
            service=web.OrderedSearch([])
            self.assertEqual(service.search('first',runtime)[0].backend,'builtin-google')
            self.assertEqual(service.search('second',runtime)[0].backend,'builtin-google')
        self.assertEqual(keyless.search.call_count,1);self.assertEqual(google.searches,['first','second'])
        self.assertTrue(any('not retried' in e[1] for e in events))

    def test_configured_provider_falls_back_but_access_and_uncertainty_stop(self):
        spec=[{'id':'primary','kind':'brave','key':'fixture'}]
        for error in (core.EndpointError(401,'{}'),core.EndpointError(403,'{}'),TimeoutError()):
            provider=MagicMock();provider.search.side_effect=error
            with patch('agentnik.search_cache.get',return_value=None),patch('agentnik.search_cache.put'),patch.object(web,'BraveWeb',return_value=provider),patch.object(web,'FirecrawlKeylessWeb',return_value=Backend()) as fallback,patch.object(web,'GoogleWeb') as google:
                service=web.OrderedSearch(spec)
                if isinstance(error,core.EndpointError) and error.status==401:
                    self.assertEqual(service.search('query',Runtime())[0].backend,'builtin-firecrawl-keyless');fallback.assert_called_once_with('')
                else:
                    with self.assertRaises(type(error)):service.search('query',Runtime())
                    fallback.assert_not_called()
                google.assert_not_called()

    def test_rejected_credential_is_not_retried_through_duplicate_profile(self):
        for status in (401,429):
            with self.subTest(status=status):
                specs=[{'id':'first','kind':'brave','key':'shared-fixture'},
                       {'id':'duplicate','kind':'brave','key':'shared-fixture'}]
                provider=MagicMock();provider.search.side_effect=core.EndpointError(status,'{}',retry_after='0')
                fallback=Backend()
                with patch('agentnik.search_cache.get',return_value=None),patch('agentnik.search_cache.put'),patch.object(web,'BraveWeb',return_value=provider),patch.object(web,'FirecrawlKeylessWeb',return_value=fallback):
                    service=web.OrderedSearch(specs)
                    service.search('first query',Runtime())
                    service.search('second query',Runtime())
                self.assertEqual(provider.search.call_count,1)
                self.assertEqual(fallback.searches,['first query','second query'])
                self.assertEqual(service.attempts[-2]['status'],'skipped')

    def test_keyless_profile_persists_without_credential_store_writes(self):
        fake=MagicMock()
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'keyring':fake}),patch.dict(os.environ,{'FIRECRAWL_API_KEY':'must-not-use'}):
            store=Store(directory)
            try:
                store.save_web_key(ident='free',kind='firecrawl-keyless',name='Free search')
                self.assertEqual(store.web_key('free'),'');self.assertNotIn('api_key',store.config['web_backends'][0]);fake.set_password.assert_not_called()
                with self.assertRaises(ValueError):store.save_web_key('bad',ident='free',kind='firecrawl-keyless')
            finally:store.db.close()
            store=Store(directory)
            try:self.assertEqual(store.config['web_backends'][0]['kind'],'firecrawl-keyless')
            finally:store.db.close()

    def test_chat_without_profiles_uses_keyless_and_strict_policy_blocks_search(self):
        config={};research.set_capability(config,C,'configured','fixture')
        self.assertEqual(routing.eligible('managed',C,config,[],'public_fetch'),'')
        self.assertTrue(routing.eligible('managed',C,config,[],'strict_public'))
        with patch.object(core,'open_request',side_effect=[Response([answer('',[call()])]),Response([answer()])]),patch.object(web,'FirecrawlKeylessWeb',return_value=Backend()) as provider,patch.object(web,'GoogleWeb') as google:
            result=research.run(C,MESSAGES,'',lambda _:None,threading.Event(),config=config,policy='Agentnik only',backends=[])
        self.assertEqual(result['status'],'ok');provider.assert_called_once_with('');google.assert_not_called()

    def test_profile_editor_allows_keyless_save_and_disables_secret_fields(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog,QComboBox,QLineEdit
        from agentnik.research_ui import SearchBackends
        app=QApplication.instance() or QApplication([]);fake=MagicMock()
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'keyring':fake}):
            store=Store(directory);manager=SearchBackends(None,store)
            def accept(dialog):
                provider=dialog.findChild(QComboBox,'searchProvider');provider.setCurrentIndex(provider.findData('firecrawl-keyless'))
                self.assertFalse(dialog.findChild(QLineEdit,'searchKey').isEnabled())
                return QDialog.DialogCode.Accepted
            try:
                with patch.object(QDialog,'exec',accept):manager.edit(True)
                self.assertEqual(store.config['web_backends'][0]['kind'],'firecrawl-keyless');fake.set_password.assert_not_called()
            finally:manager.close();app.processEvents();store.db.close()

    def test_google_challenge_after_keyless_quota_keeps_code_page_reads_available(self):
        from agentnik.code_agent import CodingRun
        from agentnik.tools import ResearchError,Source
        from test_code_agent import C as gateway,call as code_call
        from test_compat_tools import chat
        from test_routing import Wire
        with tempfile.TemporaryDirectory() as directory:
            replies=[Wire(chat(calls=[code_call('web_search',{'query':'API'})],finish='tool_calls'),False),Wire(chat(calls=[code_call('web_search',{'query':'API again'},'search2'),code_call('web_fetch',{'url':'https://example.com/docs'},'fetch')],finish='tool_calls'),False),Wire(chat('Docs reviewed'),False)]
            keyless=MagicMock();keyless.search.side_effect=core.EndpointError(429,'{}',retry_after='0')
            google=MagicMock();google.search.side_effect=ResearchError('Google Search blocked the request or requires a browser challenge')
            with patch.object(core,'open_request',side_effect=replies),patch.object(web,'FirecrawlKeylessWeb',return_value=keyless),patch.object(web,'GoogleWeb',return_value=google),patch('agentnik.code_agent.PublicWeb') as pages:
                pages.return_value.fetch.return_value=[Source('','Docs','https://example.com/docs','API guide','now')]
                events=[];CodingRun(dict(gateway,stream=False),directory,'Research',web_enabled=True,search_provider='managed').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertEqual(keyless.search.call_count,1);self.assertEqual(google.search.call_count,1);pages.return_value.fetch.assert_called_once()

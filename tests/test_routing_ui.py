"""Offline Qt route defaults, scoped opt-ins, provider links and backend credentials."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication,QDialog
    from agentnik.ui import Window,MessageBubble
    from agentnik.research_ui import SearchBackends,WebSettings,ResearchDetails
from agentnik import core,research,routing
from agentnik.storage import Store
from test_routing import C,Wire,response,message,search_call,citation


@unittest.skipUnless(HAS_QT,'PySide6 is not installed')
class RouteDesktop(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def settle(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline: self.app.processEvents(); time.sleep(.005)
        self.assertTrue(predicate()); self.app.processEvents()

    def test_global_search_preferences_apply_across_tabs_and_preserve_legacy_data(self):
        from agentnik.ui import SettingsDialog
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(root);store.config['connections']={'test':dict(C)};w=Window(store)
            try:
                w.new_session('chat','test');first=w.tabs.currentWidget()
                legacy=store.new_session('chat','test',C);legacy['research_options']={'enabled':True,'route':'managed','policy':'Provider only'};w.open_session(legacy);second=w.tabs.currentWidget()
                self.assertFalse(hasattr(first,'route_policy'));self.assertFalse(second.web_access.isChecked());self.assertEqual(second.session['research_options']['policy'],'Provider only')
                dialog=SettingsDialog(w);dialog.research_policy.setCurrentIndex(dialog.research_policy.findData('Agentnik first'));dialog.research_access.setCurrentIndex(dialog.research_access.findData('strict_public'));dialog.accept()
                self.assertEqual(routing.connection_defaults(store.config,'test',C),{'policy':'Agentnik first','access_policy':'strict_public'})
                self.assertEqual(routing.connection_defaults(store.config,'other',dict(C,model='other')),{'policy':'Agentnik first','access_policy':'strict_public'})
                settings=json.loads(store.config_path.read_text())['settings'];self.assertEqual(settings['research_policy'],'Agentnik first')
            finally:w.close();self.app.processEvents();store.db.close()

    def test_discovered_connection_capability_scope_survives_restart_and_changes_with_key(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={'env:test':dict(C,api_key='first-secret')}):
            store=Store(root);window=Window(store)
            try:
                first=dict(window.connections['env:test']);research.set_capability(store.config,first,'unsupported','Explicit rejection','hosted_search');store.flush()
            finally:window.close();self.app.processEvents();store.db.close()
            store=Store(root);window=Window(store)
            try:
                second=window.connections['env:test'];self.assertEqual(first['_capability_scope'],second['_capability_scope']);self.assertEqual(research.capability(store.config,second,'hosted_search').state,'unsupported')
                with patch.object(core,'environment_connections',return_value={'env:test':dict(C,api_key='second-secret')}):window.reload_connections()
                self.assertNotEqual(first['_capability_scope'],window.connections['env:test']['_capability_scope']);self.assertEqual(research.capability(store.config,window.connections['env:test'],'hosted_search').state,'unknown')
                self.assertNotIn('first-secret',store.config_path.read_text())
            finally:window.close();self.app.processEvents();store.db.close()

    def test_provider_only_needs_no_managed_key_and_renders_clickable_annotation(self):
        events=[{'type':'response.completed','response':response([search_call(),message(annotations=[citation()])])}]
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(core,'open_request',return_value=Wire(events)) as send:
            store=Store(root); research.set_capability(store.config,C,'configured','user','hosted_search'); w=Window(store); w.connections={'test':dict(C)}; store.config['connections']={'test':dict(C)}
            try:
                w.new_session('chat','test'); tab=w.tabs.currentWidget(); w.show(); self.app.processEvents()
                tab.web_access.setChecked(True); tab.composer.setPlainText('Find current evidence'); tab.submit()
                self.settle(lambda:tab.job is None)
                self.assertEqual(tab.session['messages'][-1]['status'],'ok'); send.assert_called_once()
                self.assertEqual(research.capability(store.config,tab.active_connection(),'hosted_search').state,'verified')
                self.assertEqual(research.capability(store.config,tab.active_connection(),'managed_tools').state,'unknown')
                bubble=tab.findChildren(MessageBubble)[-1]
                self.assertIn('href="https://example.com/"',bubble.text.toHtml())
                with patch('agentnik.ui.QDesktopServices.openUrl') as opening:
                    bubble.text.anchorClicked.emit(QUrl('https://example.com/')); opening.assert_called_once()
                details=tab.findChildren(ResearchDetails)[-1]; self.assertIn('Provider metadata only',details.excerpts.toPlainText())
                self.assertEqual(tab.model.currentText(),C['model'])
            finally: w.close(); self.app.processEvents(); store.db.close()

    def test_hosted_annotations_are_clickable_during_streaming(self):
        release=threading.Event(); waiting=threading.Event()
        initial=[{'type':'response.web_search_call.searching','item_id':'search-1'},
                 {'type':'response.output_text.delta','delta':'Answer SOURCE'},
                 {'type':'response.output_text.annotation.added','annotation':citation()}]
        boundary=sum(len(('data: '+json.dumps(v)+'\n\n').encode()) for v in initial)
        class PausedWire(Wire):
            def readline(self,*args):
                if self.tell()>=boundary and not release.is_set(): waiting.set(); release.wait(3)
                return super().readline(*args)
        wire=PausedWire(initial+[{'type':'response.completed','response':response([search_call(),message(annotations=[citation()])])}])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(core,'open_request',return_value=wire):
            store=Store(root); research.set_capability(store.config,C,'configured','user','hosted_search'); store.config['connections']={'test':dict(C)}; w=Window(store)
            try:
                w.new_session('chat','test'); tab=w.tabs.currentWidget(); w.show(); self.app.processEvents()
                tab.web_access.setChecked(True); tab.composer.setPlainText('Stream evidence'); tab.submit()
                self.settle(lambda:waiting.is_set() and 'href="https://example.com/"' in tab.live_bubble.text.toHtml())
                self.assertIsNotNone(tab.job)
                release.set(); self.settle(lambda:tab.job is None)
                self.assertEqual(tab.session['messages'][-1]['research']['annotations'][0]['source_id'],'S1')
            finally: release.set(); w.close(); self.app.processEvents(); store.db.close()

    def test_strict_default_prevents_requests_and_preserves_draft(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(core,'open_request') as send:
            store=Store(root); store.config['settings']['research_access_policy']='strict_public'; w=Window(store); w.connections={'test':dict(C)}; store.config['connections']={'test':dict(C)}
            try:
                w.new_session('chat','test'); tab=w.tabs.currentWidget(); self.app.processEvents()
                tab.web_access.setChecked(True); tab.composer.setPlainText('Keep draft'); tab.submit(); self.settle(lambda:tab.job is None)
                send.assert_not_called(); self.assertEqual(tab.composer.toPlainText(),'Keep draft')
                state=tab.session['messages'][-1]['research']; self.assertEqual(len(state['attempts']),2)
                self.assertTrue(all(a['status']=='skipped' for a in state['attempts']))
            finally: w.close(); self.app.processEvents(); store.db.close()

    def test_backend_order_and_replacement_preserve_independent_credentials(self):
        fake=MagicMock(); values={}
        fake.set_password.side_effect=lambda service,ident,key:values.__setitem__((service,ident),key)
        fake.get_password.side_effect=lambda service,ident:values.get((service,ident),'')
        with tempfile.TemporaryDirectory() as root,patch.dict('sys.modules',{'keyring':fake}),patch.dict(os.environ,{},clear=True):
            store=Store(root)
            try:
                store.save_web_key('a-key',ident='a',name='A'); store.save_web_key('b-key',ident='b',name='B')
                before={e['id']:e['credential_id'] for e in store.config['web_backends']}
                manager=SearchBackends(None,store); manager.list.setCurrentRow(0); manager.move(1)
                self.assertEqual([e['id'] for e in store.web_backend_specs()],['b','a'])
                self.assertEqual([e['key'] for e in store.web_backend_specs()],['b-key','a-key'])
                store.save_web_key('new-a-key',ident='a',name='New A')
                self.assertEqual([e['id'] for e in store.config['web_backends']],['b','a'])
                fake.delete_password.assert_called_once_with('Agentnik Web',before['a'])
                self.assertEqual(store.web_key('b'),'b-key')
                store.save_web_key(remove=True,ident='b'); self.assertEqual(store.web_key('a'),'new-a-key')
                self.assertNotIn('new-a-key',store.config_path.read_text()); manager.close()
            finally: store.db.close()


if __name__=='__main__': unittest.main()

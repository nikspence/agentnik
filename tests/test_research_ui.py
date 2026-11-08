"""Offline Qt checks for managed research lifecycle, history, and isolation."""
from dataclasses import asdict
import json
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    from PySide6.QtWidgets import QApplication,QPushButton
from agentnik import core,research
from agentnik.storage import Store
if HAS_QT:
    from agentnik.ui import Window
    from agentnik.research_ui import ResearchDetails
from test_research import Backend,C,Response,answer,call


@unittest.skipUnless(HAS_QT,"PySide6 is not installed")
class ResearchDesktop(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def settle_until(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.005)
        self.assertTrue(predicate())
        self.app.processEvents()

    def test_web_is_off_by_default_and_decision_has_no_web_controls(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(root); w=Window(store)
            try:
                w.connections={'test':dict(C)}
                w.new_session('chat','test'); first=w.tabs.currentWidget()
                w.new_session('chat','test'); second=w.tabs.currentWidget()
                self.assertFalse(first.web_access.isChecked()); self.assertFalse(second.web_access.isChecked())
                first.web_access.setChecked(True); self.assertFalse(second.web_access.isChecked())
                w.new_session('decision','test'); self.assertFalse(hasattr(w.tabs.currentWidget(),'web_access'))
            finally: w.close(); self.app.processEvents(); store.db.close()

    def test_managed_completion_sources_reopen_and_credential_free_export(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch('agentnik.web.OllamaWeb',return_value=Backend()),patch.object(core,'open_request',side_effect=[Response([answer('',[call()])]),Response([answer()])]):
            store=Store(root); store.save_web_key('private-web-key',plaintext=True)
            research.set_capability(store.config,C,'configured','user')
            w=Window(store); w.connections={'test':dict(C)}
            try:
                w.new_session('chat','test'); tab=w.tabs.currentWidget(); w.show(); self.app.processEvents()
                tab.web_access.setChecked(True); tab.composer.setPlainText('Find evidence'); tab.submit()
                self.settle_until(lambda:tab.job is None)
                self.assertEqual(len(tab.session['messages']),2)
                result=tab.session['messages'][-1]; self.assertEqual(result['status'],'ok')
                self.assertEqual(result['research']['status'],'completed'); self.assertEqual(tab.composer.toPlainText(),'')
                self.assertEqual(research.capability(store.config,C).state,'verified')
                self.assertNotIn('research_pending',tab.session)
                details=tab.findChildren(ResearchDetails)[-1]; details.toggle.click(); self.app.processEvents()
                self.assertIn('Saved evidence',details.excerpts.toPlainText())
                with patch('agentnik.research_ui.QDesktopServices.openUrl') as opening:
                    details.links.findChildren(QPushButton)[0].click(); opening.assert_called_once()
                export=Path(root)/'export.json'
                with patch('agentnik.ui.QFileDialog.getSaveFileName',return_value=(str(export),'')): tab.export_session()
                self.assertNotIn('private-web-key',export.read_text())
                saved=next(s for s in store.list_sessions() if s['id']==tab.session['id'])
                w.close_tab(w.tabs.indexOf(tab)); w.open_session(saved); self.app.processEvents()
                self.assertEqual(w.tabs.currentWidget().session['messages'][-1]['research']['sources'][0]['id'],'S1')
            finally: w.close(); self.app.processEvents(); store.db.close()

    def test_cancel_preserves_partial_state_and_rejects_late_completion(self):
        release=threading.Event(); entered=threading.Event()
        def work(c,messages,key,emit,cancel,**kwargs):
            value={'text':'Partial','thinking':'','metrics':{'input_tokens':5},'status':'failed',
                   'research':{'version':1,'run_id':kwargs['run_id'],'status':'running','sources':[],'events':[],'exchanges':[]}}
            emit(value); entered.set(); release.wait(2)
            return dict(value,text='LATE',status='ok')
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(research,'run',side_effect=work):
            store=Store(root); store.save_web_key('web-key',plaintext=True); research.set_capability(store.config,C,'configured','user')
            w=Window(store); w.connections={'test':dict(C)}
            try:
                w.new_session('chat','test'); tab=w.tabs.currentWidget(); self.app.processEvents()
                tab.web_access.setChecked(True); tab.composer.setPlainText('Keep draft'); tab.submit(); job=tab.job
                self.settle_until(lambda:entered.is_set() and tab.partial.get('text')=='Partial')
                tab.cancel(); self.assertIsNone(tab.job)
                self.assertEqual(tab.session['messages'][-1]['research']['status'],'cancelled')
                self.assertEqual(tab.composer.toPlainText(),'Keep draft')
                release.set(); job.thread.join(.5); self.app.processEvents()
                self.assertEqual(tab.session['messages'][-1]['text'],'Partial'); self.assertEqual(len(tab.session['messages']),2)
                self.assertFalse(core.chat_body(C,tab.session['messages'])['messages'])
            finally: release.set(); w.close(); self.app.processEvents(); store.db.close()

    def test_reopening_interrupted_run_never_reexecutes(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(research,'run') as run:
            store=Store(root); session=store.new_session('chat','test',C)
            session['research_pending']={'user':{'role':'user','text':'Question'},'result':{'text':'Saved partial','thinking':'','metrics':{},'research':{'version':1,'status':'running','sources':[],'events':[],'exchanges':[]}}}
            store.save(session); w=Window(store)
            try:
                w.open_session(store.list_sessions()[0]); self.app.processEvents()
                tab=w.tabs.currentWidget(); self.assertIsNone(tab.job); run.assert_not_called()
                self.assertEqual(tab.session['messages'][-1]['research']['status'],'interrupted')
                self.assertNotIn('research_pending',tab.session)
            finally: w.close(); self.app.processEvents(); store.db.close()


class WebCredentialStorage(unittest.TestCase):
    def test_independent_keyring_service_failed_replacement_and_delete(self):
        fake=MagicMock(); fake.get_password.return_value='web-secret'
        with tempfile.TemporaryDirectory() as root,patch.dict('sys.modules',{'keyring':fake}),patch.dict(os.environ,{'OLLAMA_API_KEY':'inference-only'},clear=True):
            store=Store(root)
            try:
                self.assertEqual(store.web_key(),'')
                store.save_web_key('web-secret'); old=store.config['web_backends'][0]['credential_id']
                fake.set_password.assert_called_once_with('Agentnik Web',old,'web-secret')
                self.assertNotIn('web-secret',store.config_path.read_text()); self.assertEqual(store.web_key(),'web-secret')
                fake.set_password.side_effect=RuntimeError('keyring unavailable')
                with self.assertRaises(RuntimeError): store.save_web_key('replacement')
                self.assertEqual(store.config['web_backends'][0]['credential_id'],old)
                store.save_web_key(remove=True); fake.delete_password.assert_called_once_with('Agentnik Web',old)
                self.assertEqual(store.config['web_backends'],[])
            finally: store.db.close()


if __name__=='__main__': unittest.main()

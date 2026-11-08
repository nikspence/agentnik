"""Offscreen Agentnik-owned coding UI and role selection, with mock models."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from agentnik import core
from agentnik.storage import Store
from test_routing import Wire
from test_compat_tools import chat
from test_code_agent import call

class CodingWorkspace(unittest.TestCase):
    def test_missing_saved_connection_is_preserved_on_reopen(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident)
                session['coding_models']={'heavy':{'connection':'Missing','model':'saved-alias'}};store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();app.processEvents();tab.save_models()
                self.assertIn('unavailable',tab.roles['heavy'][0].currentText())
                self.assertEqual(tab.session['coding_models']['heavy'],{'connection':'Missing','model':'saved-alias'})
                with self.assertRaises(ValueError):tab.role_connection('heavy')
            finally:window.close();app.processEvents();store.db.close()

    def test_failed_run_can_be_saved_and_reopened(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['connections']={'Gateway':{'url':'https://gateway.example/v1','protocol':'chat','model':'heavy','stream':False}}
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();tab.roles['heavy'][0].setCurrentIndex(tab.roles['heavy'][0].findData('Gateway'))
                tab.composer.setPlainText('Analyze')
                with patch.object(core,'open_request',side_effect=core.EndpointError(401,'private error')):
                    tab.start_coding();deadline=time.monotonic()+3
                    while tab.job is not None and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    self.assertIsNone(tab.job)
                saved=next(s for s in store.list_sessions() if s['id']==session['id'])
                self.assertEqual(saved['code_state'],'failed');self.assertNotIn('private error',json.dumps(saved))
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents()
                self.assertEqual(window.tabs.currentWidget().composer.toPlainText(),'Analyze')
                self.assertIn('Coding stopped',window.tabs.currentWidget().activity.toPlainText())
            finally:window.close();app.processEvents();store.db.close()

    def test_selected_connection_edits_only_after_approval_and_restores_roles(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        def settle(predicate):
            deadline=time.monotonic()+3
            while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            store.config['connections']={'Gateway':{'url':'https://gateway.example/v1','protocol':'chat','model':'heavy-default','api_key':'private-model-key','stream':False}}
            window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();app.processEvents()
                for role,model in [('heavy','my-heavy-coder'),('light','my-light-coder')]:
                    combo,field=tab.roles[role];combo.setCurrentIndex(combo.findData('Gateway'));field.setText(model)
                tab.light_enabled.setChecked(False)
                tab.composer.setPlainText('Create a test file')
                replies=[Wire(chat(calls=[call('write_file',{'path':'test.txt','content':'approved content'})],finish='tool_calls'),False),Wire(chat('Created test.txt'),False)]
                with patch.object(core,'open_request',side_effect=replies) as endpoint,patch('subprocess.Popen') as process:
                    tab.start_coding();settle(lambda:tab.approve.isEnabled())
                    self.assertFalse((project/'test.txt').exists());self.assertIn('approved content',tab.diff.toPlainText())
                    self.assertIn('Not checked',tab.approval.toPlainText());tab.decide(True);settle(lambda:tab.job is None)
                    self.assertEqual((project/'test.txt').read_text(),'approved content');self.assertEqual(endpoint.call_count,2);process.assert_not_called()
                saved=next(s for s in store.list_sessions() if s['id']==session['id'])
                self.assertNotIn('private-model-key',json.dumps(saved))
                self.assertEqual(saved['coding_context']['task'],'Create a test file')
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents()
                reopened=window.tabs.currentWidget();self.assertEqual(reopened.roles['heavy'][1].text(),'my-heavy-coder')
                self.assertEqual(reopened.roles['light'][1].text(),'my-light-coder');self.assertFalse(reopened.light_enabled.isChecked());self.assertIsNone(reopened.job)
                self.assertIn('Created test.txt',reopened.context_view.toPlainText());self.assertFalse(reopened.use_context.isChecked())
                reopened.use_context.setChecked(True);reopened.composer.setPlainText('Follow up');bodies=[]
                def reply(c,url,body,timeout):bodies.append(body);return Wire(chat('Follow-up complete'),False)
                with patch.object(core,'open_request',side_effect=reply):
                    reopened.start_coding();settle(lambda:reopened.job is None)
                self.assertIn('Create a test file',json.dumps(bodies[0]));self.assertIn('Created test.txt',json.dumps(bodies[0]))
                self.assertFalse(reopened.use_context.isChecked())
            finally:window.close();app.processEvents();store.db.close()

if __name__=='__main__':unittest.main()

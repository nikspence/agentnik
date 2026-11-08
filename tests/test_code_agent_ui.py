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
                tab.composer.setPlainText('Create a test file')
                replies=[Wire(chat(calls=[call('write_file',{'path':'test.txt','content':'approved content'})],finish='tool_calls'),False),Wire(chat('Created test.txt'),False)]
                with patch.object(core,'open_request',side_effect=replies) as endpoint,patch('subprocess.Popen') as process:
                    tab.start_coding();settle(lambda:tab.approve.isEnabled())
                    self.assertFalse((project/'test.txt').exists());self.assertIn('approved content',tab.diff.toPlainText())
                    self.assertIn('Not checked',tab.approval.toPlainText());tab.decide(True);settle(lambda:tab.job is None)
                    self.assertEqual((project/'test.txt').read_text(),'approved content');self.assertEqual(endpoint.call_count,2);process.assert_not_called()
                saved=next(s for s in store.list_sessions() if s['id']==session['id'])
                self.assertNotIn('private-model-key',json.dumps(saved))
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents()
                reopened=window.tabs.currentWidget();self.assertEqual(reopened.roles['heavy'][1].text(),'my-heavy-coder')
                self.assertEqual(reopened.roles['light'][1].text(),'my-light-coder');self.assertIsNone(reopened.job)
            finally:window.close();app.processEvents();store.db.close()

if __name__=='__main__':unittest.main()

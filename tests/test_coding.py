"""Coding prompt history and persistence in offscreen Qt."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from agentnik import core
from agentnik.storage import Store


class PromptHistory(unittest.TestCase):
    def test_navigation_drafts_multiline_and_reopen(self):
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);window.show();app.processEvents()
                tab=window.tabs.currentWidget()
                image=store.attach(data=b'image');tab.attachments.set_paths([image]);tab.documents=[{'name':'notes.txt','text':'Example document'}];tab.refresh_documents();tab.save_draft()
                tab.remember_prompt('first\nsecond line');tab.composer.setPlainText('second prompt');tab.light_enabled.setChecked(False)
                with patch.object(tab,'role_connection',return_value={'model':'heavy','url':'http://localhost','protocol':'chat'}),patch('agentnik.code_ui.CodingRun') as run,patch.object(tab,'launch') as launch:
                    tab.start_coding();launch.assert_called_once();self.assertEqual(run.call_args.args[2],'second prompt')
                    self.assertEqual(run.call_args.kwargs['images'],[image]);self.assertEqual(run.call_args.kwargs['documents'][0]['name'],'notes.txt')
                tab.composer.setPlainText('unsent draft');QTest.keyClick(tab.composer,Qt.Key.Key_Up)
                self.assertEqual(tab.composer.toPlainText(),'second prompt')
                tab.history_up.click();self.assertEqual(tab.composer.toPlainText(),'first\nsecond line')
                # Up within a multiline prompt moves the cursor, not the history.
                QTest.keyClick(tab.composer,Qt.Key.Key_Up);self.assertEqual(tab._history_index,0)
                tab.composer.setPlainText('edited first');tab.history_down.click();self.assertEqual(tab.composer.toPlainText(),'second prompt')
                tab.history_down.click();self.assertEqual(tab.composer.toPlainText(),'unsent draft')
                tab.history_up.click();tab.history_up.click();self.assertEqual(tab.composer.toPlainText(),'edited first')
                tab.history_down.click();tab.history_down.click()
                saved=next(row for row in store.list_sessions() if row['id']==session['id'])
                self.assertEqual(saved['coding_prompt_history'],['first\nsecond line','second prompt'])
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents();tab=window.tabs.currentWidget()
                self.assertEqual(tab.composer.toPlainText(),'unsent draft');tab.history_up.click();self.assertEqual(tab.composer.toPlainText(),'second prompt')
                self.assertEqual(tab.attachments.paths,[image]);self.assertEqual(tab.documents[0]['text'],'Example document')
                self.assertFalse(hasattr(tab,'simulate'))
            finally:window.close();app.processEvents();store.db.close()

    def test_session_history_validation(self):
        from agentnik.sessions import validate_session,SessionError
        with tempfile.TemporaryDirectory() as directory:
            from agentnik.repositories import RepositoryRegistry
            store=Store(Path(directory)/'data')
            try:
                registry=RepositoryRegistry(store);ident=registry.put(directory);session=registry.session(ident)
                session['coding_prompt_history']=['one','two'];self.assertEqual(validate_session(session)['coding_prompt_history'],['one','two'])
                session['coding_prompt_history']=['']
                with self.assertRaises(SessionError):validate_session(session)
            finally:store.db.close()

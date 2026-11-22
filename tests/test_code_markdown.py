import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from agentnik import core
from agentnik.storage import Store
from agentnik.ui import Window
from agentnik.code_ui import CodeActivity

class CodeMarkdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_responses_render_markdown_but_tool_activity_remains_literal(self):
        view=CodeActivity();view.load_events([{'kind':'output','text':'Tool **literal**'}, {'kind':'model_markdown','text':'# Heading\n\n**bo'}, {'kind':'model_markdown','text':'ld**\n\n```python\nprint(1)\n```'}],lambda e:e['text'])
        self.assertIn('Tool **literal**',view.toPlainText());self.assertIn('Heading',view.toPlainText());self.assertIn('bold',view.toPlainText());self.assertNotIn('**bold**',view.toPlainText())
        html=view.toHtml();self.assertIn('font-weight:700',html);self.assertIn('print(1)',html)
        self.assertIsNone(view.loadResource(QTextDocument.ResourceType.ImageResource,QUrl('file:///private.png')))
        view.close()

    def test_markdown_persists_across_session_reload(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);folder=root/'project';folder.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(folder);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();tab.record('output','Tool **literal**');tab.job=object();tab.run_id='test';tab.receive({'run_id':'test','kind':'model_response','role':'Model','model':'test','text':'**long answer**'});tab.job=None;self.app.processEvents()
                self.assertIn('long answer',tab.activity.toPlainText());self.assertNotIn('**long answer**',tab.activity.toPlainText())
                saved=next(row for row in store.list_sessions() if row['id']==session['id']);window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);self.app.processEvents()
                view=window.tabs.currentWidget().activity;self.assertIn('long answer',view.toPlainText());self.assertIn('Tool **literal**',view.toPlainText());self.assertIn('font-weight:700',view.toHtml())
            finally:window.close();self.app.processEvents();store.db.close()

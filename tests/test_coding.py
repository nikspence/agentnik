"""Coding prompt history and persistence in offscreen Qt."""
import os
import hashlib
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


    def test_legacy_review_data_is_preserved_without_ui(self):
        from agentnik.ui import Window
        from PySide6.QtWidgets import QDialog,QPlainTextEdit,QComboBox,QLineEdit,QPushButton,QMessageBox
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);app.processEvents();tab=window.tabs.currentWidget()
                spec=project/'spec.md';spec.write_text('spec',encoding='utf-8');evidence=project/'source.txt';evidence.write_text('evidence',encoding='utf-8')
                finding={'id':'finding-1','severity':'high','title':'Gap','rationale':'No test criterion','location':'spec.md:1','assumptions':'','verification':'Ask owner'}
                review={'id':'a'*32+'-1','role':'repository_fit','model':'reviewer','path':'spec.md','source_sha256':hashlib.sha256(b'spec').hexdigest(),'payload_sha256':'c'*64,'evidence':[{'path':'source.txt','sha256':hashlib.sha256(b'evidence').hexdigest(),'payload_sha256':'d'*64}],'track_context':{'id':'missing_track','digest':'e'*64},'pass_status':'completed','structured':{'status':'valid','findings':[finding]},'dispositions':{'finding-1':{'status':'contested','rationale':'Need clarification'}}}
                failed=dict(review,id='a'*32+'-2',pass_status='failed',structured={'status':'not_available','findings':[]},dispositions={})
                pending=dict(review,id='a'*32+'-3',pass_status='interrupted',structured={'status':'not_available','findings':[]},dispositions={})
                session['coding_review_history']=[{'version':1,'id':'b'*32,'track_id':None,'reviews':[review,failed,pending]}];store.save(session)
                evidence.unlink();saved=store.list_sessions()[0]
                from agentnik.sessions import validate_session,SessionError
                import copy
                legacy=copy.deepcopy(saved);legacy['coding_review_history'][0]['reviews']=legacy['coding_review_history'][0]['reviews'][:1];legacy['coding_review_history'][0]['reviews'][0].pop('pass_status')
                self.assertEqual(validate_session(legacy)['coding_review_history'][0]['reviews'][0]['structured']['status'],'valid')
                broken=copy.deepcopy(saved);broken['coding_review_history'][0]['version']=2
                with self.assertRaises(SessionError):validate_session(broken)
                broken=copy.deepcopy(saved);broken['coding_review_history'][0]['reviews'][0]['dispositions']['finding-1']['status']='approved'
                with self.assertRaises(SessionError):validate_session(broken)
                broken=copy.deepcopy(saved);broken['coding_review_history'][0]['reviews'][1]['pass_status']='completed'
                with self.assertRaises(SessionError):validate_session(broken)
                broken=copy.deepcopy(saved);broken['coding_review_history']*=11
                with self.assertRaises(SessionError):validate_session(broken)
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents();tab=window.tabs.currentWidget();self.assertFalse(hasattr(tab,'saved_reviews_button'))
                self.assertEqual(store.list_sessions()[0]['coding_review_history'],saved['coding_review_history'])
            finally:window.close();app.processEvents();store.db.close()

    def test_navigation_drafts_multiline_and_reopen(self):
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);window.show();app.processEvents()
                tab=window.tabs.currentWidget()
                image=store.attach(data=b'image');tab.attachments.set_paths([image]);tab.documents=[{'name':'notes.txt','text':'Example document'}];tab.refresh_documents();tab.save_draft()
                tab.remember_prompt('first\nsecond line');tab.composer.setPlainText('second prompt')
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
                session['coding_steering_draft']='pending instruction';self.assertEqual(validate_session(session)['coding_steering_draft'],'pending instruction')
                for invalid in (123,'x'*16001):
                    session['coding_steering_draft']=invalid
                    with self.assertRaises(SessionError):validate_session(session)
                session.pop('coding_steering_draft')
                session['coding_save_review_progress']='yes'
                with self.assertRaises(SessionError):validate_session(session)
                session.pop('coding_save_review_progress')
                session['coding_prompt_history']=['']
                with self.assertRaises(SessionError):validate_session(session)
            finally:store.db.close()

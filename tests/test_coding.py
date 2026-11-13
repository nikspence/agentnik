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
    def test_parallel_review_findings_view_is_bounded_and_session_local(self):
        from agentnik.ui import Window
        from PySide6.QtWidgets import QDialog,QPlainTextEdit,QComboBox,QLineEdit,QPushButton,QMessageBox
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);app.processEvents();tab=window.tabs.currentWidget()
                spec=project/'spec.md';spec.write_text('spec',encoding='utf-8');evidence=project/'source.txt';evidence.write_text('evidence',encoding='utf-8')
                tab.job=object();tab.run_id='active';finding={'id':'finding-1','severity':'high','title':'Gap','rationale':'No test criterion','location':'spec.md:1','assumptions':'','verification':'Ask owner'}
                review={'id':'a'*32+'-1','role':'design','model':'reviewer','path':'spec.md','source_sha256':hashlib.sha256(b'spec').hexdigest(),'payload_sha256':'c'*64,'evidence':[{'path':'source.txt','sha256':hashlib.sha256(b'evidence').hexdigest(),'payload_sha256':'d'*64}],'track_context':{'id':'missing_track','digest':'e'*64},'pass_status':'completed','structured':{'status':'valid','findings':[finding]}}
                tab.receive({'run_id':'other','kind':'independent_review_result','review':review});self.assertFalse(tab.review_results)
                tab.receive({'run_id':'active','kind':'independent_review_result','review':review});self.assertTrue(tab.review_results_button.isEnabled())
                displayed=[]
                def inspect(dialog):displayed.append(dialog.findChild(QPlainTextEdit).toPlainText());return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',inspect):tab.show_review_results()
                self.assertIn('No test criterion',displayed[0]);self.assertIn('Current source hashes match',displayed[0]);self.assertIn('Track run context changed or is unavailable',displayed[0]);self.assertNotIn('review_results',store.list_sessions()[0])
                def set_disposition(dialog):
                    box=dialog.findChild(QComboBox,'reviewDisposition');box.setCurrentIndex(box.findData('contested'))
                    dialog.findChild(QLineEdit,'reviewDispositionReason').setText('Need clarification')
                    dialog.findChild(QPushButton,'saveReviewDisposition').click();return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',set_disposition):tab.show_review_results()
                self.assertEqual(tab.review_dispositions[(review['id'],'finding-1')],{'status':'contested','rationale':'Need clarification'})
                with patch.object(QDialog,'exec',inspect):tab.show_review_results()
                self.assertIn('contested',displayed[-1]);self.assertIn('Need clarification',displayed[-1])
                evidence.write_text('changed',encoding='utf-8')
                with patch.object(QDialog,'exec',inspect):tab.show_review_results()
                self.assertIn('Stale or unavailable',displayed[-1]);self.assertIn('No test criterion',displayed[-1])
                evidence.unlink()
                with patch.object(QDialog,'exec',inspect):tab.show_review_results()
                self.assertIn('Stale or unavailable',displayed[-1])
                invalid=dict(review,id='d'*32+'-1',structured={'status':'valid','findings':[dict(finding,id='finding-9')]})
                tab.receive({'run_id':'active','kind':'independent_review_result','review':invalid});self.assertEqual(len(tab.review_results),1)
                failed=dict(review,id='a'*32+'-2',pass_status='failed',structured={'status':'not_available','findings':[]})
                tab.receive({'run_id':'active','kind':'independent_review_result','review':failed});self.assertEqual(len(tab.review_results),2)
                pending=dict(review,id='a'*32+'-3',pass_status='pending',structured={'status':'not_available','findings':[]})
                tab.receive({'run_id':'active','kind':'independent_review_result','review':pending});tab.stop_subagents('cancelled')
                self.assertEqual(tab.review_results[pending['id']]['pass_status'],'interrupted')
                tab.job=None
                def save_snapshot(dialog):dialog.findChild(QPushButton,'saveReviewSnapshot').click();return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',save_snapshot):tab.show_review_results()
                saved=store.list_sessions()[0];self.assertEqual(saved['coding_review_history'][0]['reviews'][0]['dispositions']['finding-1']['status'],'contested')
                self.assertEqual(saved['coding_review_history'][0]['reviews'][0]['track_context'],review['track_context'])
                self.assertEqual(saved['coding_review_history'][0]['reviews'][1]['pass_status'],'failed')
                self.assertEqual(saved['coding_review_history'][0]['reviews'][2]['pass_status'],'interrupted')
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
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);app.processEvents();tab=window.tabs.currentWidget();self.assertFalse(tab.review_results);self.assertTrue(tab.saved_reviews_button.isEnabled())
                with patch.object(QDialog,'exec',inspect):tab.show_saved_reviews()
                self.assertIn('Stale or unavailable',displayed[-1]);self.assertIn('Need clarification',displayed[-1]);self.assertIn('failed',displayed[-1]);self.assertIn('Track run context changed or is unavailable',displayed[-1])
                def revise_saved(dialog):
                    box=dialog.findChild(QComboBox,'savedReviewDisposition');box.setCurrentIndex(box.findData('deferred'))
                    dialog.findChild(QLineEdit,'savedReviewRationale').setText('Revisit later')
                    dialog.findChild(QPushButton,'saveReviewRevision').click();return QDialog.DialogCode.Rejected
                with patch.object(QMessageBox,'warning'),patch.object(store,'save',side_effect=OSError('simulated failure')),patch.object(QDialog,'exec',revise_saved):tab.show_saved_reviews()
                self.assertEqual(len(store.list_sessions()[0]['coding_review_history']),1)
                with patch.object(QDialog,'exec',revise_saved):tab.show_saved_reviews()
                history=store.list_sessions()[0]['coding_review_history'];self.assertEqual(len(history),2)
                self.assertEqual(history[0]['reviews'][0]['dispositions']['finding-1']['status'],'contested')
                self.assertEqual(history[1]['reviews'][0]['dispositions']['finding-1'],{'status':'deferred','rationale':'Revisit later'})
                self.assertNotEqual(history[0]['id'],history[1]['id'])
                def delete_revision(dialog):
                    dialog.findChild(QComboBox,'savedReviewChoice').setCurrentIndex(1);dialog.findChild(QPushButton,'deleteSavedReview').click();return QDialog.DialogCode.Rejected
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(QDialog,'exec',delete_revision):tab.show_saved_reviews()
                self.assertEqual(len(store.list_sessions()[0]['coding_review_history']),1)
                second=copy.deepcopy(tab.session['coding_review_history'][0]);second['id']='e'*32
                tab.session['coding_review_history'].append(second);store.save(tab.session)
                def delete_second(dialog):
                    dialog.findChild(QComboBox,'savedReviewChoice').setCurrentIndex(1)
                    dialog.findChild(QPushButton,'deleteSavedReview').click();return QDialog.DialogCode.Rejected
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No),patch.object(QDialog,'exec',delete_second):tab.show_saved_reviews()
                self.assertEqual(len(store.list_sessions()[0]['coding_review_history']),2)
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(QMessageBox,'warning'),patch.object(store,'save',side_effect=OSError('simulated failure')),patch.object(QDialog,'exec',delete_second):tab.show_saved_reviews()
                self.assertEqual(len(store.list_sessions()[0]['coding_review_history']),2);self.assertEqual(len(tab.session['coding_review_history']),2)
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(QDialog,'exec',delete_second):tab.show_saved_reviews()
                remaining=store.list_sessions()[0]['coding_review_history'];self.assertEqual(len(remaining),1);self.assertNotEqual(remaining[0]['id'],second['id']);self.assertTrue(tab.saved_reviews_button.isEnabled())
                def delete_last(dialog):dialog.findChild(QPushButton,'deleteSavedReview').click();return QDialog.DialogCode.Rejected
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(QDialog,'exec',delete_last):tab.show_saved_reviews()
                self.assertEqual(store.list_sessions()[0]['coding_review_history'],[]);self.assertFalse(tab.saved_reviews_button.isEnabled())
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

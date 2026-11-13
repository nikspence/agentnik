"""Explicit local review snapshot export with no network or replacement."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agentnik import core
from agentnik.review_export import prepare_review_export,write_new_review_export


def snapshot():
    return {'version':1,'id':'a'*32,'track_id':None,'reviews':[{'id':'b'*32+'-1','role':'design','model':'model','path':'spec.md','source_sha256':'c'*64,'payload_sha256':'d'*64,'evidence':[],'pass_status':'completed','structured':{'status':'valid','findings':[]},'dispositions':{}}]}


class ReviewExport(unittest.TestCase):
    def test_validated_export_blocks_secrets_and_existing_files(self):
        record=snapshot();content=prepare_review_export(record,['private-key'])
        self.assertEqual(json.loads(content),{'format':'agentnik-review-snapshot','version':1,'snapshot':record})
        record['reviews'][0]['model']='private-key'
        with self.assertRaises(ValueError):prepare_review_export(record,['private-key'])
        record['version']=2
        with self.assertRaises(ValueError):prepare_review_export(record)
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'review.json';write_new_review_export(target,content);self.assertEqual(target.read_text(encoding='utf-8'),content)
            with self.assertRaises(FileExistsError):write_new_review_export(target,'replacement')
            self.assertEqual(target.read_text(encoding='utf-8'),content)

    def test_offscreen_preview_export_cancel_and_changed_snapshot(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog,QFileDialog,QMessageBox,QPlainTextEdit,QPushButton
        from agentnik.ui import Window
        from agentnik.storage import Store
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            project=Path(root)/'project';project.mkdir();store=Store(Path(root)/'data');window=Window(store);target=Path(root)/'review.json'
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['coding_review_history']=[snapshot()];store.save(session);window.open_session(session);tab=window.tabs.currentWidget();seen=[];mode=['cancel']
                def interact(dialog):
                    if dialog.windowTitle()=='Export review snapshot':
                        seen.append(dialog.findChild(QPlainTextEdit,'reviewExportPreview').toPlainText())
                        if mode[0]=='cancel':return QDialog.DialogCode.Rejected
                        if mode[0]=='changed':tab.session['coding_review_history'][0]['reviews'][0]['model']='changed'
                        if mode[0]=='credentials':window.connections['Sensitive']={'api_key':'model'}
                        return QDialog.DialogCode.Accepted
                    dialog.findChild(QPushButton,'exportReviewSnapshot').click();return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',interact),patch.object(QFileDialog,'getSaveFileName',return_value=(str(target),'JSON')),patch.object(QMessageBox,'information'),patch.object(QMessageBox,'warning') as warning,patch.object(core,'open_request') as request:
                    tab.show_saved_reviews();self.assertFalse(target.exists())
                    mode[0]='changed';tab.show_saved_reviews();self.assertFalse(target.exists());warning.assert_called_once()
                    tab.session['coding_review_history']=[snapshot()];mode[0]='credentials';tab.show_saved_reviews();self.assertFalse(target.exists());del window.connections['Sensitive']
                    mode[0]='save';tab.show_saved_reviews();self.assertTrue(target.exists());request.assert_not_called()
                    self.assertEqual(json.loads(seen[-1])['snapshot'],snapshot());self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['snapshot'],snapshot())
                    mode[0]='save';tab.show_saved_reviews();self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['snapshot'],snapshot())
            finally:window.close();app.processEvents();store.db.close()


"""Offline coding context compaction and pre-run behavior."""
import copy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from agentnik import core
from agentnik.storage import Store
from agentnik.context_compaction import coding_snapshot,coding_effective_context

CONNECTION={'url':'https://example.test/v1','model':'model','protocol':'chat','stream':False}

class CodingCompactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_context_and_model_settings_open_in_dialogs_and_persist(self):
        from PySide6.QtCore import QTimer
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                self.assertIs(tab.roles['heavy'][0].window(),window)
                def context():
                    dialog=self.app.activeModalWidget();self.assertIs(tab.coding_auto_compact.window(),dialog)
                    tab.coding_auto_compact.setChecked(False);dialog.reject()
                QTimer.singleShot(0,context);tab.edit_coding_context()
                self.assertFalse(tab.session['coding_auto_compact'])
                self.assertTrue(tab.coding_auto_compact.isHidden())
                QTimer.singleShot(0,lambda:self.app.activeModalWidget().reject());tab.edit_coding_context()
                saved=store.list_sessions()[0];self.assertFalse(saved['coding_auto_compact'])
            finally:window.close();self.app.processEvents();store.db.close()

    def test_terminal_desktop_code_defaults_preserve_explicit_session_choices(self):
        from agentnik.code_settings import configure_code
        from agentnik.ui import Window

        with tempfile.TemporaryDirectory() as directory, patch.object(core,'discover',return_value={}), patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data')
            configure_code(store,['desktop-code','auto-compact','off'])
            configure_code(store,['desktop-code','thinking','on'])
            self.assertIn('image inspection default: off',configure_code(store,['desktop-code','vision']))
            configure_code(store,['desktop-code','vision','on'])
            self.assertIn('image inspection default: on',configure_code(store,['desktop-code']))
            self.assertIn('model thinking display default: on',configure_code(store,['desktop-code']))
            self.assertIn('auto-compaction default: off',configure_code(store,['desktop-code']))
            store.db.close()
            store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project)
                first=window.repositories.session(ident)
                store.save(first);window.open_session(first)
                self.assertFalse(window.tabs.currentWidget().coding_auto_compact.isChecked())
                self.assertTrue(window.tabs.currentWidget().show_thinking.isChecked())
                self.assertTrue(window.tabs.currentWidget().vision_enabled.isChecked())
                second=window.repositories.session(ident)
                second['coding_auto_compact']=True
                second['coding_show_thinking']=False
                second['coding_vision_enabled']=False
                store.save(second);window.open_session(second)
                self.assertTrue(window.tabs.currentWidget().coding_auto_compact.isChecked())
                self.assertFalse(window.tabs.currentWidget().show_thinking.isChecked())
                self.assertFalse(window.tabs.currentWidget().vision_enabled.isChecked())
            finally:
                window.close();self.app.processEvents();store.db.close()

    def test_summary_is_bound_to_original(self):
        context={'task':'Original task','answer':'Original answer'};saved=copy.deepcopy(context);snap=coding_snapshot(context,'Summary')
        self.assertEqual(coding_effective_context(context,snap)['answer'],'Summary');self.assertEqual(context,saved)
        context['answer']='changed'
        with self.assertRaises(ValueError):coding_effective_context(context,snap)

    def test_auto_compacts_before_followup_and_preserves_original(self):
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);context={'task':'T'*1600,'answer':'A'*1600};session['coding_context']=context;store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                tab.composer.setPlainText('Next task');tab.use_context.setChecked(True)
                with patch.object(tab,'role_connection',return_value=CONNECTION),patch.object(core,'run_request',return_value={'text':'Important findings','thinking':'','metrics':{}}) as request,patch('agentnik.code_ui.CodingRun') as run,patch.object(tab,'launch') as launch:
                    tab.start_coding();deadline=time.monotonic()+4
                    while (tab.job or not launch.called) and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
                self.assertEqual(request.call_count,1);launch.assert_called_once();self.assertEqual(run.call_args.kwargs['context']['answer'],'Important findings')
                self.assertEqual(tab.session['coding_context'],context);saved=store.list_sessions()[0];self.assertEqual(saved['coding_compaction']['summary'],'Important findings')
            finally:window.close();self.app.processEvents();store.db.close()

    def test_cancellation_does_not_start_run_or_save_late_result(self):
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store);release=threading.Event();started=threading.Event()
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['coding_context']={'task':'T'*1600,'answer':'A'*1600};store.save(session);window.open_session(session);tab=window.tabs.currentWidget();tab.composer.setPlainText('Next');tab.use_context.setChecked(True)
                def request(*args):started.set();release.wait(2);return {'text':'Late summary'}
                with patch.object(tab,'role_connection',return_value=CONNECTION),patch.object(core,'run_request',side_effect=request),patch.object(tab,'launch') as launch:
                    tab.start_coding();self.assertTrue(started.wait(1));tab.cancel();release.set()
                    deadline=time.monotonic()+.2
                    while time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
                    launch.assert_not_called();self.assertNotIn('coding_compaction',tab.session);self.assertEqual(tab.composer.toPlainText(),'Next')
            finally:release.set();window.close();self.app.processEvents();store.db.close()

    def test_edit_and_restore_context_in_manager(self):
        import json
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QPlainTextEdit,QPushButton
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);session['coding_context']={'task':'Original','answer':'Answer'};store.save(session);window.open_session(session);tab=window.tabs.currentWidget()
                def edit():
                    dialog=self.app.activeModalWidget();fields=dialog.findChildren(QPlainTextEdit);fields[0].setPlainText(json.dumps({'task':'Edited','answer':'Answer'}));fields[1].setPlainText('Saved summary')
                    next(b for b in dialog.findChildren(QPushButton) if b.text()=='Save context').click()
                QTimer.singleShot(0,edit);tab.edit_coding_context()
                saved=store.list_sessions()[0];self.assertEqual(saved['coding_context']['task'],'Edited');self.assertEqual(saved['coding_compaction']['summary'],'Saved summary')
                def restore():
                    dialog=self.app.activeModalWidget();buttons=dialog.findChildren(QPushButton);next(b for b in buttons if b.text()=='Use original context').click();next(b for b in buttons if b.text()=='Save context').click()
                QTimer.singleShot(0,restore);tab.edit_coding_context();self.assertNotIn('coding_compaction',store.list_sessions()[0])
            finally:window.close();self.app.processEvents();store.db.close()

    def test_failed_compaction_preserves_context_and_does_not_launch(self):
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);project=root/'project';project.mkdir();store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(project);session=window.repositories.session(ident);context={'task':'T'*1600,'answer':'A'*1600};session['coding_context']=context;store.save(session);window.open_session(session);tab=window.tabs.currentWidget();tab.composer.setPlainText('Follow up');tab.use_context.setChecked(True)
                with patch.object(tab,'role_connection',return_value=CONNECTION),patch.object(core,'run_request',side_effect=ValueError('unavailable')),patch.object(tab,'launch') as launch:
                    tab.start_coding();deadline=time.monotonic()+3
                    while tab.job and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
                    launch.assert_not_called()
                self.assertEqual(tab.session['coding_context'],context);self.assertNotIn('coding_compaction',tab.session);self.assertEqual(tab.composer.toPlainText(),'Follow up')
            finally:window.close();self.app.processEvents();store.db.close()

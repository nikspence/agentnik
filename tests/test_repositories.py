"""Offline passive repository/Code workspace acceptance checks."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik import core
from agentnik.storage import Store
from agentnik.repositories import RepositoryRegistry


class Registry(unittest.TestCase):
    def test_ordinary_and_git_folders_duplicates_rename_relocate_and_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);a=root/'plain';b=root/'git';c=root/'relocated'
            for path in (a,b,c):path.mkdir()
            (b/'.git').mkdir();marker=a/'keep.txt';marker.write_text('keep')
            store=Store(root/'data');registry=RepositoryRegistry(store)
            try:
                ident=registry.put(a);other=registry.put(b)
                with self.assertRaises(ValueError):registry.put(a/'.')
                session=registry.session(ident);store.save(session)
                registry.rename(ident,'Renamed');registry.put(c,'Renamed',ident)
                self.assertEqual(registry.get(ident)['path'],str(c.resolve()))
                self.assertEqual(store.list_sessions()[0]['path_snapshot'],str(a.resolve()))
                registry.remove(ident);self.assertTrue(marker.exists())
                self.assertEqual(store.list_sessions()[0]['project_id'],ident)
                self.assertEqual(registry.list()[0]['id'],other)
            finally:store.db.close()
            store=Store(root/'data')
            try:self.assertEqual(RepositoryRegistry(store).list()[0]['id'],other)
            finally:store.db.close()

    def test_missing_folder_can_be_renamed_but_cannot_start_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'project';folder.mkdir()
            store=Store(root/'data');registry=RepositoryRegistry(store)
            try:
                ident=registry.put(folder);folder.rmdir()
                self.assertFalse(registry.get(ident)['available']);registry.rename(ident,'Still here')
                with self.assertRaises(OSError):registry.session(ident)
                folder.mkdir();self.assertEqual(registry.session(ident)['version'],4)
            finally:store.db.close()


class WorkspaceUI(unittest.TestCase):
    def test_picker_cancel_independent_drafts_and_reopen_do_not_execute(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from agentnik.ui import Window
        from agentnik.code_ui import CodeTab,RepositoryPicker
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]),patch.object(core,'open_request') as network,patch('subprocess.Popen') as process:
            root=Path(directory);folder=root/'project';folder.mkdir()
            store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(folder,'Project')
                with patch('agentnik.ui.RepositoryPicker') as picker:
                    picker.return_value.exec.return_value=QDialog.DialogCode.Rejected
                    window.new_code();self.assertEqual(store.list_sessions(),[])
                picker=RepositoryPicker(window,window.repositories);picker.search.setText('not-present');self.assertEqual(picker.items.count(),0)
                picker.search.setText('Project');self.assertEqual(picker.items.count(),1);picker.choose();self.assertEqual(picker.selected_id,ident)
                for theme in ('Light','Dark'):
                    window.theme.setCurrentText(theme)
                    session=window.repositories.session(ident);store.save(session);window.open_session(session)
                    tab=window.tabs.currentWidget();self.assertIsInstance(tab,CodeTab)
                    tab.composer.setPlainText('Draft '+theme);window.show();app.processEvents()
                    self.assertFalse(tab.grab().isNull())
                self.assertEqual(len(store.list_sessions()),2)
                current=window.tabs.currentWidget();saved_id=current.session['id'];window.close_tab(window.tabs.indexOf(current))
                saved=next(s for s in store.list_sessions() if s['id']==saved_id);window.repositories.remove(ident)
                window.open_session(saved);app.processEvents()
                self.assertEqual(window.tabs.currentWidget().composer.toPlainText(),'Draft Dark')
                self.assertEqual(window.tabs.widget(0).composer.toPlainText(),'Draft Light')
                network.assert_not_called();process.assert_not_called()
            finally:window.close();app.processEvents();store.db.close()

    def test_missing_snapshot_reopens_without_changing_directory(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QLabel
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(directory);folder=root/'old';folder.mkdir();replacement=root/'new';replacement.mkdir()
            store=Store(root/'data');window=Window(store)
            try:
                ident=window.repositories.put(folder);session=window.repositories.session(ident);store.save(session)
                folder.rmdir();window.repositories.put(replacement,'Relocated',ident)
                window.open_session(store.list_sessions()[0]);app.processEvents()
                tab=window.tabs.currentWidget();self.assertEqual(tab.session['path_snapshot'],str(folder))
                text=' '.join(label.text() for label in tab.findChildren(QLabel))
                self.assertIn('missing or unavailable',text);self.assertIn('retains its original path',text)
            finally:window.close();app.processEvents();store.db.close()


if __name__=='__main__':unittest.main()

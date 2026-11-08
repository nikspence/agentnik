"""Offline locale selection, fallback, and Qt catalog loading checks."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from agentnik import localization,core
from agentnik.storage import Store


class Localization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_locale_selection_and_missing_or_corrupt_catalog_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            self.assertEqual(localization.locale_candidates('zh_TW'),['zh-Hant'])
            self.assertEqual(localization.locale_candidates('zh-Hans-CN'),['zh-Hans'])
            self.assertIsNone(localization.install(self.app,'system',directory,['ko-KR']))
            (directory/'agentnik_ko.qm').write_bytes(b'invalid catalog')
            self.assertIsNone(localization.install(self.app,'ko',directory))
            self.assertIsNone(localization.install(self.app,'system',directory,['en-US','ko-KR']))
            self.assertIn(('ko','한국어'),localization.choices(directory))

    def test_language_setting_persists_and_does_not_change_history(self):
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(tmp);session=store.new_session('chat','Example',{});session['draft']='Original text';store.save(session)
            window=Window(store)
            try:
                window.language.setCurrentIndex(window.language.findData('en'))
                self.assertIn('restart',window.statusBar().currentMessage().lower())
            finally:window.close();self.app.processEvents();store.db.close()
            store=Store(tmp)
            try:
                self.assertEqual(store.config['settings']['language'],'en')
                self.assertEqual(store.list_sessions()[0]['draft'],'Original text')
            finally:store.db.close()


if __name__=='__main__':unittest.main()

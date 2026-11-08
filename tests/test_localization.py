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
            self.assertIn(('ko','한국어 (미리보기)'),localization.choices(directory))

    def test_korean_catalog_loads_and_translates_visible_picker(self):
        from agentnik.code_ui import RepositoryPicker
        from agentnik.repositories import RepositoryRegistry
        translator=localization.install(self.app,'ko')
        self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);folder=root/'project';folder.mkdir();store=Store(root/'data');registry=RepositoryRegistry(store)
                try:
                    registry.put(folder,'User project');picker=RepositoryPicker(None,registry)
                    self.assertEqual(picker.windowTitle(),'저장소 선택')
                    self.assertEqual(picker.search.placeholderText(),'프로젝트 이름 및 경로 검색')
                    self.assertIn('User project',picker.items.item(0).text());picker.close()
                finally:store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_main_window_labels(self):
        from agentnik.ui import Window
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
                store=Store(tmp);window=Window(store)
                try:
                    self.assertEqual(window.search.placeholderText(),'대화 검색')
                    self.assertEqual(window.tabs.tabText(0),'시작')
                    self.assertGreaterEqual(window.language.findData('ko'),0)
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_chat_controls_preserve_user_text(self):
        from agentnik.ui import Window,MessageBubble
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
                store=Store(tmp);store.config['connections']={'Example':{'url':'https://example.test/v1','model':'model','protocol':'chat'}}
                window=Window(store)
                try:
                    window.new_session('chat','Example');tab=window.tabs.currentWidget()
                    self.assertEqual(tab.send_button.text(),'전송');self.assertEqual(tab.cancel_button.text(),'취소')
                    self.assertEqual(tab.web_access.text(),'웹 접근');self.assertEqual(tab.reasoning.placeholderText(),'추론 수준')
                    tab.composer.setPlainText('User text');tab.save_draft();self.assertEqual(store.list_sessions()[0]['draft'],'User text')
                    bubble=MessageBubble({'role':'assistant','text':'Answer','thinking':'Reasoning'})
                    bubble.thinking_toggle.setChecked(True);self.assertEqual(bubble.thinking_toggle.text(),'사고 과정 숨기기')
                    bubble.close()
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

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

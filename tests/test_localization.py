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

    def test_korean_coding_approval_preserves_paths_and_diff(self):
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
                root=Path(tmp);folder=root/'project';folder.mkdir();store=Store(root/'data');window=Window(store)
                try:
                    ident=window.repositories.put(folder);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                    tab=window.tabs.currentWidget();self.assertEqual(tab.send.text(),'코딩 작업 실행');self.assertEqual(tab.approve.text(),'제안된 단계 승인')
                    run=CodingRun({'model':'test'},str(folder),'task');tab.job=run;tab.run_id=run.run_id
                    tab.receive({'run_id':run.run_id,'kind':'edit_proposal','fingerprint':'one','proposal':{'cwd':str(folder),'path':'src/file.py','diff':'+exact text'}})
                    text=tab.approval.toPlainText();self.assertIn('확인되지 않음',text);self.assertIn(str(folder),text);self.assertIn('src/file.py',text)
                    self.assertEqual(tab.diff.toPlainText(),'+exact text');tab.cancel()
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_decision_form_preserves_request_values(self):
        from agentnik.ui import Window,DecisionResult
        from PySide6.QtWidgets import QLabel
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
                store=Store(tmp);store.config['connections']={'Example':{'url':'https://example.test/v1','model':'model','protocol':'chat'}};window=Window(store)
                try:
                    window.new_session('decision','Example');tab=window.tabs.currentWidget();question=tab.questions[0]
                    self.assertEqual(tab.send_button.text(),'결정 실행');self.assertEqual(question.kind.itemText(1),'객관식')
                    question.name.setText('priority');question.kind.setCurrentIndex(1);question.instructions.setPlainText('Choose');question.add_option(['a','First']);question.add_option(['b','Second']);tab.state.setPlainText('Context')
                    body=core.decision_body({'model':'model'},tab.form_value())
                    self.assertEqual(list(body['questions']['priority']['criteria'].items()),[('a','First'),('b','Second')])
                    result=DecisionResult({'answers':{'q':{'noul':0.7,'confidence':0.8}}})
                    labels=[label.text() for label in result.findChildren(QLabel)]
                    self.assertIn('예',labels);self.assertIn('아니요',labels);self.assertIn('신뢰도: 80.00%',labels);result.close()
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_connection_editor_preserves_connection_values(self):
        from agentnik.ui import ConnectionDialog
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            dialog=ConnectionDialog(None,'Example',{'url':'https://example.test/v1','api_key':'test-key','model':'alias','protocol':'messages','context_limit':4096,'stream':False})
            try:
                self.assertEqual(dialog.windowTitle(),'연결')
                self.assertEqual(dialog.layout().labelForField(dialog.fields['url']).text(),'엔드포인트 URL')
                self.assertIn('일반 텍스트',dialog.plain.text());self.assertFalse(dialog.plain.isChecked())
                name,value=dialog.value();self.assertEqual(name,'Example')
                self.assertEqual(value['url'],'https://example.test/v1');self.assertEqual(value['api_key'],'test-key')
                self.assertEqual(value['model'],'alias');self.assertEqual(value['protocol'],'messages')
                self.assertEqual(value['context_limit'],4096);self.assertFalse(value['stream'])
            finally:dialog.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_web_settings_preserve_navigation_policy_values(self):
        from agentnik.ui import Window
        from agentnik.research_ui import WebSettings,ResearchDetails
        from agentnik import routing
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
                store=Store(tmp);connection={'url':'https://example.test/v1','model':'model','protocol':'chat'}
                store.config['connections']={'Example':connection};window=Window(store)
                try:
                    window.new_session('chat','Example');tab=window.tabs.currentWidget();dialog=WebSettings(tab,connection)
                    try:
                        self.assertEqual(dialog.windowTitle(),'웹 조사')
                        dialog.access_policy.setCurrentIndex(dialog.access_policy.findData('strict_public'))
                        self.assertIn('공개',dialog.access_policy.currentText());self.assertEqual(dialog.access_policy.currentData(),'strict_public')
                        self.assertEqual(dialog.default_policy.currentText(),'제공자 우선');self.assertEqual(dialog.default_policy.currentData(),'Provider first')
                        dialog.default_policy.setCurrentIndex(dialog.default_policy.findData('Agentnik only'))
                        routing.save_defaults(store.config,'Example',connection,dialog.default_policy.currentData(),dialog.access_policy.currentData())
                        defaults=routing.connection_defaults(store.config,'Example',connection)
                        self.assertEqual(defaults['policy'],'Agentnik only');self.assertEqual(defaults['access_policy'],'strict_public')
                        tab.route_policy.setCurrentIndex(tab.route_policy.findData('Provider only'));tab.save_draft()
                        self.assertEqual(tab.session['research_options']['policy'],'Provider only')
                        self.assertFalse(dialog.plain.isChecked());self.assertFalse(dialog.allow.isChecked())
                        details=ResearchDetails({'route':'managed','status':'completed','sources':[],'events':[],'unverified_annotations':1})
                        self.assertIn('Agentnik 관리형',details.toggle.text());self.assertIn('확인할 수 없습니다',details.excerpts.toPlainText());details.close()
                    finally:dialog.close()
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

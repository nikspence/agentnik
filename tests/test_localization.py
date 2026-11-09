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
                    self.assertEqual(window.font_smaller.accessibleName(),'글꼴 크기 줄이기')
                    window.apply_font_size(15);self.assertIn('15포인트',window.font_larger.toolTip())
                    with patch('agentnik.ui.error') as error:window.open_session({'_unavailable':True})
                    self.assertIn('원본 데이터',error.call_args.args[1]);self.assertIn('history.sqlite3',error.call_args.args[1])
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_chat_controls_preserve_user_text(self):
        from agentnik.ui import Window,MessageBubble,metrics_text
        from PySide6.QtWidgets import QPushButton
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
                    tab.session['messages']=[{'role':'user','text':'Earlier prompt'}];tab.composer.clear();tab.render()
                    message=tab.findChildren(MessageBubble)[0]
                    edit=next(b for b in message.findChildren(QPushButton) if b.accessibleName()=='프롬프트 수정 후 다시 보내기')
                    edit.click();self.assertEqual(tab.composer.toPlainText(),'Earlier prompt');self.assertEqual(len(tab.session['messages']),1)
                    star=next(b for b in message.findChildren(QPushButton) if b.accessibleName()=='프롬프트 저장')
                    with patch('agentnik.ui.QInputDialog.getText',return_value=('',True)): star.click()
                    self.assertEqual(star.accessibleName(),'저장된 프롬프트 제거')
                    bubble=MessageBubble({'role':'assistant','text':'Answer','thinking':'Reasoning'})
                    bubble.thinking_toggle.setChecked(True);self.assertEqual(bubble.thinking_toggle.text(),'사고 과정 숨기기')
                    bubble.close()
                    metrics=metrics_text({'input_tokens':80,'output_tokens':20,'total_seconds':4,'model_requests':2,'usage_complete':False})
                    self.assertIn('프롬프트 80 토큰',metrics);self.assertIn('전체 25.00 토큰/초',metrics)
                    self.assertIn('알려진 사용량만',metrics);self.assertIn('—',metrics)
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_attachments_keep_file_path_and_filter(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage,QColor
        from agentnik.ui import AttachmentBox
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);image=QImage(8,8,QImage.Format.Format_RGB32);image.fill(QColor('red'))
                path=root/'original.png';self.assertTrue(image.save(str(path)));store=Store(root/'data');box=AttachmentBox(store)
                try:
                    with patch('agentnik.ui.QFileDialog.getOpenFileNames',return_value=([str(path)],'')) as picker:box.choose()
                    self.assertEqual(picker.call_args.args[1],'이미지 첨부');self.assertIn('*.png',picker.call_args.args[3])
                    self.assertEqual(box.list.item(0).text(),'이미지 1')
                    self.assertEqual(box.list.item(0).data(Qt.ItemDataRole.UserRole),box.paths[0]);self.assertTrue(Path(box.paths[0]).exists())
                finally:box.close();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_coding_approval_preserves_paths_and_diff(self):
        from agentnik.ui import Window
        from agentnik.code_agent import CodingRun
        from agentnik.coding import SimulationRun
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
                root=Path(tmp);folder=root/'project';folder.mkdir();store=Store(root/'data');window=Window(store)
                try:
                    ident=window.repositories.put(folder);session=window.repositories.session(ident)
                    session['coding_context']={'task':'Keep {user} text','answer':'Original answer'};store.save(session);window.open_session(session)
                    tab=window.tabs.currentWidget();self.assertEqual(tab.send.text(),'실행');self.assertEqual(tab.approve.text(),'제안된 단계 승인')
                    self.assertIn('이전 작업:',tab.context_view.toPlainText());self.assertIn('Keep {user} text',tab.context_view.toPlainText())
                    window.stats();self.assertIn('준비됨',window.statusBar().currentMessage());self.assertIn(session['project_name'],window.statusBar().currentMessage())
                    self.assertIn('model/{x}',tab.activity_text({'kind':'output','text':'Heavy task: requesting model/{x} through the selected connection.'}))
                    self.assertIn('위임',tab.activity_text({'kind':'output','text':'Light task delegated to model/light through its configured connection.'}))
                    self.assertIn('src/{name}.py',tab.activity_text({'kind':'output','text':'Applied approved edit: src/{name}.py'}))
                    self.assertEqual(tab.activity_text({'kind':'finished','text':'Applied approved edit: text'}),'Applied approved edit: text')
                    usage='Usage: Heavy: 2 request(s), input 10 (known usage only), output unknown tokens; Light: 1 request(s), input 3, output 0 tokens'
                    tab.record('usage',usage);display=tab.activity.toPlainText()
                    self.assertIn('고성능: 요청 2회',display);self.assertIn('입력 10 (알려진 사용량만)',display);self.assertIn('출력 알 수 없음',display)
                    self.assertIn('경량: 요청 1회',display);self.assertEqual(store.list_sessions()[0]['code_activity'][-1]['text'],usage)
                    malformed='Usage: unexpected';self.assertEqual(tab.activity_text({'kind':'usage','text':malformed}),malformed)
                    run=CodingRun({'model':'test'},str(folder),'task');tab.job=run;tab.run_id=run.run_id
                    tab.receive({'run_id':run.run_id,'kind':'edit_proposal','fingerprint':'one','proposal':{'cwd':str(folder),'path':'src/file.py','diff':'+exact text'}})
                    text=tab.approval.toPlainText();self.assertIn('확인되지 않음',text);self.assertIn(str(folder),text);self.assertIn('src/file.py',text)
                    self.assertIn('파일 수정 승인 대기 중: src/file.py',tab.activity.toPlainText())
                    self.assertEqual(store.list_sessions()[0]['code_activity'][-1]['text'],'Awaiting approval for file edit: src/file.py')
                    self.assertEqual(tab.diff.toPlainText(),'+exact text');tab.cancel()
                    simulated=SimulationRun(str(folder));tab.job=simulated;tab.run_id=simulated.run_id
                    tab.receive({'run_id':simulated.run_id,'kind':'proposal','fingerprint':'sim','proposal':{'cwd':str(folder),'argv':['git','status']},'recommendation':'Not checked'})
                    self.assertIn('시뮬레이션 전용',tab.approval.toPlainText());self.assertIn(str(folder),tab.approval.toPlainText())
                    self.assertIn('"git", "status"',tab.approval.toPlainText());self.assertIn('Not checked',tab.approval.toPlainText());tab.cancel()
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

    def test_korean_session_dialogs_preserve_selected_names(self):
        from agentnik.ui import Window
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
                store=Store(tmp);store.config['connections']={'My connection':{'url':'https://example.test/v1','model':'alias','protocol':'chat'}};window=Window(store)
                try:
                    with patch('agentnik.ui.QInputDialog.getItem',return_value=('My connection',True)) as picker:window.new_session('chat')
                    self.assertEqual(picker.call_args.args[1:3],('새 채팅','연결:'))
                    self.assertEqual(window.tabs.currentWidget().session['connection_name'],'My connection')
                    window.history.setCurrentRow(0)
                    with patch('agentnik.ui.QInputDialog.getText',return_value=('My {title}',True)) as rename:window.rename()
                    self.assertEqual(rename.call_args.args[1:3],('세션 이름 바꾸기','제목:'))
                    self.assertEqual(store.list_sessions()[0]['title'],'My {title}')
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_web_settings_preserve_navigation_policy_values(self):
        from agentnik.ui import Window
        from agentnik.research_ui import WebSettings,ResearchDetails
        from agentnik import routing
        from PySide6.QtWidgets import QLabel
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
                store=Store(tmp);connection={'url':'https://example.test/v1','model':'model','protocol':'chat'}
                store.config['connections']={'Example':connection};window=Window(store)
                try:
                    window.new_session('chat','Example');tab=window.tabs.currentWidget();dialog=WebSettings(tab,connection)
                    try:
                        self.assertEqual(dialog.windowTitle(),'웹 조사')
                        texts=[label.text() for label in dialog.findChildren(QLabel)]
                        self.assertTrue(any('모델: model' in text and '설정일 뿐 검증이 아닙니다' in text for text in texts))
                        self.assertTrue(any('429/503' in text and '요청당 45초' in text for text in texts))
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

    def test_korean_backend_removal_confirmation_preserves_profile_on_no(self):
        from PySide6.QtWidgets import QMessageBox,QPushButton
        from agentnik.research_ui import SearchBackends
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                store=Store(tmp);store.save_web_key('test-key',plaintext=True,ident='test',name='User profile')
                manager=SearchBackends(None,store)
                try:
                    self.assertEqual(manager.windowTitle(),'검색 백엔드');self.assertEqual(manager.list.item(0).text(),'User profile')
                    self.assertIn('제거',[b.text() for b in manager.findChildren(QPushButton)])
                    with patch('agentnik.research_ui.QMessageBox.question',return_value=QMessageBox.StandardButton.No) as question:
                        manager.remove()
                    self.assertIn('자격 증명',question.call_args.args[2]);self.assertEqual(store.web_key('test'),'test-key')
                    self.assertEqual(store.config['web_backends'][0]['name'],'User profile')
                finally:manager.close();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_research_sources_preserve_evidence(self):
        from agentnik.research_ui import ResearchDetails
        from PySide6.QtWidgets import QPushButton
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            data={'route':'managed','status':'completed','events':[],'sources':[
                {'id':'S1','url':'https://example.com/page','title':'Original title','retrieved_at':'2026-01-01','backend':'search','excerpt':'Original {evidence}','truncated':True},
                {'id':'S2','url':'https://example.com/metadata','title':'Other title','reported_at':'2026-01-02','backend':'hosted','metadata_only':True}]}
            details=ResearchDetails(data)
            try:
                self.assertIn('완료',details.toggle.text());text=details.excerpts.toPlainText()
                self.assertIn('일부 생략',text);self.assertIn('메타데이터만',text);self.assertIn('Original {evidence}',text)
                self.assertIn('2026-01-01',text);self.assertIn('https://example.com/page',text)
                self.assertEqual(details.links.findChildren(QPushButton)[0].text(),'[S1] Original title')
            finally:details.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_research_completion_preserves_saved_result(self):
        from agentnik.ui import Window
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
                store=Store(tmp);store.config['connections']={'Example':{'url':'https://example.test/v1','model':'model','protocol':'chat'}};window=Window(store)
                try:
                    window.new_session('chat','Example');tab=window.tabs.currentWidget();tab.pending={'role':'user','text':'Question','images':[]}
                    tab.research_connection=tab.active_connection()
                    result={'status':'ok','text':'Original answer','thinking':'','metrics':{},'research':{'version':2,'status':'completed','route':'managed','sources':[],'events':[{'kind':'route_switch','detail':'switch'}],'retention':{'truncated':True}}}
                    tab.complete_research(result)
                    self.assertIn('조사 완료',tab.info.text());self.assertIn('경로가 변경',tab.info.text());self.assertIn('새 채팅',tab.info.text())
                    self.assertEqual(store.list_sessions()[0]['messages'][-1]['text'],'Original answer')
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_history_confirmation_decline_preserves_history(self):
        from agentnik.ui import Window
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
                store=Store(tmp);session=store.new_session('chat','Example',{});session['draft']='Keep';store.save(session);window=Window(store)
                try:
                    with patch('agentnik.ui.confirm',return_value=False) as confirm:window.clear_all()
                    self.assertIn('모든 채팅',confirm.call_args.args[1]);self.assertEqual(store.list_sessions()[0]['draft'],'Keep')
                finally:window.close();self.app.processEvents();store.db.close()
        finally:self.app.removeTranslator(translator)

    def test_korean_catalog_preserves_named_placeholders(self):
        import string
        import xml.etree.ElementTree as ET
        path=Path(__file__).resolve().parents[1]/'agentnik'/'translations'/'agentnik_ko.ts'
        formatter=string.Formatter()
        def fields(text):return sorted(field for _,field,_,_ in formatter.parse(text or '') if field is not None)
        for message in ET.parse(path).findall('.//message'):
            source=message.findtext('source');translation=message.find('translation')
            if translation.get('type') not in ('unfinished','vanished','obsolete'):
                self.assertEqual(fields(source),fields(translation.text),source)

    def test_korean_import_duplicate_actions(self):
        import json
        from agentnik.ui import Window,Connections
        translator=localization.install(self.app,'ko');self.assertIsNotNone(translator)
        try:
            for choice in ('건너뛰기','바꾸기','이름 바꾸기'):
                with self.subTest(choice=choice),tempfile.TemporaryDirectory() as tmp,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
                    root=Path(tmp);source=root/'import.json';source.write_text(json.dumps({'connections':{'Example':{'url':'https://new.test/v1','protocol':'chat'}}}),encoding='utf-8')
                    store=Store(root/'data');store.save_connection('Example',{'url':'https://old.test/v1','protocol':'chat'});window=Window(store);dialog=Connections(window)
                    try:
                        with patch('agentnik.ui.QFileDialog.getOpenFileName',return_value=(str(source),'')),patch('agentnik.ui.confirm',return_value=True),patch('agentnik.ui.QInputDialog.getItem',return_value=(choice,True)),patch('agentnik.ui.QInputDialog.getText',return_value=('New name',True)):
                            dialog.import_file()
                        saved=store.config['connections']
                        self.assertEqual(saved['Example']['url'],'https://new.test/v1' if choice=='바꾸기' else 'https://old.test/v1')
                        self.assertEqual('New name' in saved,choice=='이름 바꾸기')
                    finally:dialog.close();window.close();self.app.processEvents();store.db.close()
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

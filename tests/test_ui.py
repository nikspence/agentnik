"""Offscreen Qt integration checks. Install requirements to enable these."""
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT = importlib.util.find_spec('PySide6') is not None

@unittest.skipUnless(HAS_QT,'PySide6 is not installed')
class Desktop(unittest.TestCase):
    def test_direct_mantle_connection_displays_catalog_and_inference_routes(self):
        from agentnik.ui import ConnectionDialog
        dialog=ConnectionDialog(None,'Mantle',{'url':'https://bedrock-mantle.us-east-1.api.aws/openai/v1','protocol':'responses'})
        try:
            self.assertFalse(dialog.route_hint.isHidden())
            self.assertIn('https://bedrock-mantle.us-east-1.api.aws/v1/models',dialog.route_hint.text())
            self.assertIn('https://bedrock-mantle.us-east-1.api.aws/openai/v1/responses',dialog.route_hint.text())
            dialog.protocol.setCurrentText('messages');dialog.fields['url'].setText('https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages')
            self.assertIn('Inference: https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages',dialog.route_hint.text())
            name,c=dialog.value();self.assertEqual(c['url'],'https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages')
            dialog.fields['url'].setText('https://gateway.example/v1');self.assertTrue(dialog.route_hint.isHidden())
        finally:dialog.close()

    def test_toolbar_controls_and_appearance_settings(self):
        from PySide6.QtWidgets import QToolBar
        from agentnik.storage import Store
        from agentnik.ui import Window,SettingsDialog
        with tempfile.TemporaryDirectory() as root,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(root);window=Window(store)
            try:
                window.resize(1320,850);window.show();self.app.processEvents()
                bars=window.findChildren(QToolBar);self.assertEqual(len(bars),2)
                right=bars[1];self.assertTrue(right.geometry().y()>bars[0].geometry().y() or right.geometry().x()>bars[0].geometry().x())
                self.assertEqual([action.text() for action in bars[0].actions()[1:]],['☰ History','☆ Prompts','＋ Chat','＋ Code','Repositories','Connections','MCP servers'])
                self.assertEqual(right.actions()[0],window.settings_action);self.assertEqual([right.widgetForAction(action) for action in right.actions()[1:]],[window.font_smaller,window.font_larger,window.web_search,window.mcp_access]);self.assertEqual(window.web_search.text(),'Web Access')
                self.assertTrue(window.font_smaller.isVisible());self.assertTrue(window.font_larger.isVisible());self.assertTrue(window.web_search.isVisible());self.assertTrue(right.widgetForAction(window.settings_action).isVisible())
                from PySide6.QtCore import Qt
                from PySide6.QtTest import QTest
                self.assertFalse(window.web_search.isChecked());QTest.mouseClick(window.web_search,Qt.MouseButton.LeftButton);self.assertTrue(store.config['settings']['web_search_enabled'])
                window.web_search.setFocus();QTest.keyClick(window.web_search,Qt.Key.Key_Space);self.assertFalse(store.config['settings']['web_search_enabled'])
                self.assertTrue(window.mcp_access.isChecked());window.mcp_access.click();self.assertFalse(store.config['settings']['mcp_access_enabled']);window.mcp_access.click();self.assertTrue(store.config['settings']['mcp_access_enabled'])
                dialog=SettingsDialog(window);dialog.theme.setCurrentIndex(dialog.theme.findData('Dark'));dialog.language.setCurrentIndex(dialog.language.findData('en'));dialog.reject()
                self.assertNotEqual(store.config['settings'].get('theme'),'Dark');self.assertNotEqual(store.config['settings'].get('language'),'en')
                dialog=SettingsDialog(window);dialog.theme.setCurrentIndex(dialog.theme.findData('Dark'));dialog.language.setCurrentIndex(dialog.language.findData('en'));dialog.mcp_priority.setCurrentIndex(dialog.mcp_priority.findData('last'));dialog.accept()
                self.assertEqual(store.config['settings']['theme'],'Dark');self.assertEqual(store.config['settings']['language'],'en');self.assertEqual(store.config['settings']['mcp_priority'],'last');self.assertEqual(window.brand_variant,'dark')
            finally:window.close();self.app.processEvents();store.db.close()

    def test_initial_window_frame_fits_available_screen(self):
        from agentnik.storage import Store
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as root,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(root);window=Window(store)
            try:
                window.show();self.app.processEvents();area=window.screen().availableGeometry()
                self.assertTrue(area.contains(window.frameGeometry()),(area,window.frameGeometry()))
            finally:window.close();self.app.processEvents();store.db.close()

    def test_model_count_only_appears_in_status_bar(self):
        from agentnik.storage import Store
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}), patch('agentnik.core.models',return_value=[]):
            store=Store(root);store.config['connections']={'first':{'url':'http://localhost:11434/v1','model':'one'}};window=Window(store)
            try:
                window.new_session('chat','first');tab=window.tabs.currentWidget();window.show();self.app.processEvents()
                tab.info.setText('123 model(s) available.')
                self.assertTrue(tab.info.isHidden())
                self.assertEqual(window.session_status.text(),'123 model(s) available.')
                self.assertTrue(tab.connection.isVisible())
            finally:
                window.close();self.app.processEvents();store.db.close()

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        font=self.app.font(); font.setPointSize(9); self.app.setFont(font)
    def test_copy_assistant_response_from_history_and_stream(self):
        from agentnik.storage import Store
        from agentnik.ui import Window,MessageBubble
        previous=self.app.clipboard().text()
        with tempfile.TemporaryDirectory() as root,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}),patch('agentnik.core.models',return_value=[]):
            store=Store(root);window=Window(store)
            try:
                session=store.new_session('chat','Test',{});session['messages']=[{'role':'user','text':'Question'},{'role':'assistant','text':'**Answer**\nSecond line','thinking':'Private thinking'}];store.save(session)
                window.open_session(store.list_sessions()[0]);tab=window.tabs.currentWidget();bubbles=tab.findChildren(MessageBubble)
                self.assertFalse(hasattr(bubbles[0],'copy_button'));bubbles[1].copy_button.click()
                self.assertEqual(self.app.clipboard().text(),'**Answer**\nSecond line')
                live=MessageBubble({'role':'assistant','text':'','thinking':'Reasoning'},live=True)
                self.assertFalse(live.copy_button.isEnabled());live.set_stream('Partial','Reasoning');live.copy_button.click()
                self.assertEqual(self.app.clipboard().text(),'Partial');live.set_stream('Complete','Reasoning');live.copy_button.click()
                self.assertEqual(self.app.clipboard().text(),'Complete');live.close()
            finally:
                window.close();self.app.processEvents();store.db.close();self.app.clipboard().setText(previous)
    def test_forms_tabs_charts_and_history(self):
        from agentnik.storage import Store
        from agentnik.ui import Window, SessionTab, Connections, DecisionResult
        with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}):
            store=Store(root); store.config['connections']={'local':{'url':'http://localhost:11434/v1','protocol':'chat','model':'test'}}
            with patch.object(store,'connections',return_value=store.config['connections']):
                w=Window(store); w.show(); self.app.processEvents()
                manager=Connections(w); self.assertEqual(manager.list.count(),1); manager.close()
                w.new_session('chat','local'); chat=w.tabs.currentWidget(); self.assertIsInstance(chat,SessionTab)
                chat.composer.setPlainText('draft'); chat.save_draft()
                legacy=store.new_session('decision','local',store.config['connections']['local']);legacy['form']['state']='Preserved state';store.save(legacy)
                store.save_prompt('decision',legacy['form'],'Saved decision');w.open_session(legacy);decision=w.tabs.currentWidget()
                self.assertTrue(decision.view.isReadOnly());self.assertIn('Preserved state',decision.view.toPlainText());self.assertIn('Saved decision',decision.view.toPlainText())
                self.assertEqual(len(store.list_sessions()),2)
                w.new_session('decision','local');self.assertEqual(len(store.list_sessions()),2)
                raw={'answers':{'q':{'type':'choice','choice':'a','probabilities':{'a':.8,'b':.2},'confidence':.6}}}
                chart=DecisionResult(raw); chart.resize(650,400); chart.show(); self.app.processEvents(); self.assertFalse(chart.grab().isNull()); chart.close()
                w.toggle_history(); self.assertFalse(w.sidebar.isVisible()); w.toggle_history()
                w.delete_ids([decision.session['id']]); self.assertEqual(len(store.list_sessions()),1)
                self.assertEqual(chat.composer.toPlainText(),'draft')
                w.close(); self.app.processEvents(); store.db.close()
    def test_saved_decision_prompts_remain_read_only_without_a_session(self):
        from PySide6.QtWidgets import QDialog,QPlainTextEdit,QPushButton
        from agentnik.storage import Store
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as root,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(root);legacy=store.new_session('decision','local',{});legacy['form']['state']='Preserved prompt';store.save_prompt('decision',legacy['form'],'Old prompt')
            window=Window(store)
            try:
                self.assertFalse(any('＋ Decision' in action.text() for action in window.findChildren(__import__('PySide6.QtGui',fromlist=['QAction']).QAction)))
                self.assertTrue(any(button.text()=='View saved Decision prompts…' for button in window.findChildren(QPushButton)))
                def inspect(dialog):
                    view=dialog.findChild(QPlainTextEdit,'legacyDecisionPrompts');self.assertTrue(view.isReadOnly());self.assertIn('Preserved prompt',view.toPlainText());return QDialog.DialogCode.Rejected
                with patch.object(QDialog,'exec',inspect):window.show_legacy_decision_prompts()
                self.assertEqual(len(store.list_prompts('decision')),1);self.assertEqual(store.list_sessions(),[])
            finally:window.close();self.app.processEvents();store.db.close()
    def test_job_delivery_uses_gui_thread(self):
        from PySide6.QtCore import QThread
        from agentnik.ui import Job
        result=[]
        job=Job(lambda *_:42,lambda v:result.append((v,QThread.currentThread())),lambda e:self.fail(e))
        deadline=time.monotonic()+3
        while not result and time.monotonic()<deadline:
            self.app.processEvents(); time.sleep(.01)
        self.assertEqual(result[0][0],42); self.assertEqual(result[0][1],self.app.thread())

    def test_chat_sizes_font_settings_and_inline_thinking(self):
        from agentnik.storage import Store
        from agentnik.ui import Window, MessageBubble, MessageText, metrics_text
        def settle():
            for _ in range(25): self.app.processEvents()
        with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}):
            store=Store(root)
            w=Window(store)
            try:
                w.connections={'local':{'url':'http://localhost:11434/v1','model':'test'}}
                session=store.new_session('chat','local',w.connections['local'])
                session['messages']=[{'role':'user','text':'Hi'}, {'role':'assistant','text':'# Long reply\n\n'+('\n\n'.join(['A long paragraph of wrapped prose. '*8]*20)), 'thinking':'Reasoning text'}]
                w.open_session(session); w.show(); settle(); tab=w.tabs.currentWidget()
                bubbles=tab.findChildren(MessageBubble)
                short,long=bubbles
                self.assertLess(short.text.height(),50)
                self.assertGreater(long.text.height(),500)
                self.assertEqual(long.text.verticalScrollBar().maximum(),0)
                self.assertGreater(short.parentWidget().layout().contentsMargins().left(),long.parentWidget().layout().contentsMargins().left())
                self.assertFalse(long.thinking_view.isVisible()); long.thinking_toggle.click(); settle(); self.assertTrue(long.thinking_view.isVisible())
                long.thinking_toggle.click(); self.assertFalse(long.thinking_view.isVisible())
                self.assertLessEqual(tab.composer.height(),80)
                tab.chat_split.setSizes([350,180]); settle(); self.assertGreater(tab.composer.height(),100)
                # Toolbar font controls apply immediately and persist the size.
                self.assertTrue(w.menuBar().isHidden() or not w.menuBar().actions())
                w.apply_font_size(15); w.font_larger.click(); store.config['settings']['theme']='Dark'; w.apply_theme(); settle()
                self.assertEqual(short.text.font().pointSize(),16)
                self.assertEqual(short.text.document().defaultFont().pointSize(),16)
                self.assertEqual(store.config['settings']['font_size'],16)
                self.assertEqual(store.config['settings']['theme'],'Dark')
                w.font_smaller.click(); settle(); self.assertEqual(short.text.font().pointSize(),15)
                self.assertEqual(store.config['settings']['font_size'],15)
                self.assertEqual(long.text.verticalScrollBar().maximum(),0)
                w.resize(1000,700); settle(); self.assertEqual(long.text.verticalScrollBar().maximum(),0)
                # A live assistant card reveals reasoning once and respects subsequent toggles.
                live=tab.add_bubble({'role':'assistant','text':'','thinking':''},live=True); settle()
                live.set_stream('','Reasoning arrives'); settle(); self.assertTrue(live.thinking_view.isVisible())
                live.thinking_toggle.click(); live.set_stream('**Answer**','More reasoning'); settle()
                self.assertFalse(live.thinking_view.isVisible()); self.assertEqual(live.text.toPlainText(),'Answer')
                live.text.set_content('```python\n'+'x'*1000+'\n```',True); settle()
                self.assertEqual(live.text.horizontalScrollBar().maximum(),0)
                self.assertEqual(live.text.verticalScrollBar().maximum(),0)
                self.assertIn('Overall 25.00 tok/s',metrics_text({'input_tokens':80,'output_tokens':20,'total_seconds':4}))
                self.assertNotIn('Overall',metrics_text({'input_tokens':80,'output_tokens':20,'total_seconds':4,'prompt_tps':100,'generation_tps':10}))
            finally:
                w.close(); self.app.processEvents(); store.db.close()

    def test_edit_and_resend_restores_images_and_appends_a_new_turn(self):
        import copy
        from PySide6.QtWidgets import QPushButton
        from agentnik.storage import Store
        from agentnik.ui import Window, MessageBubble
        from agentnik import core
        with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}), patch('agentnik.core.models',return_value=[]), patch('agentnik.core.run_request') as request:
            store=Store(root); w=Window(store)
            try:
                c={'url':'https://example.com/v1','protocol':'chat','model':'test'}
                image=store.attach(data=b'image')
                session=store.new_session('chat','test',c)
                session['messages']=[{'role':'user','text':'Original prompt','images':[image]},{'role':'assistant','text':'Original answer'}]
                original=copy.deepcopy(session['messages'])
                w.connections={'test':c}; w.open_session(session); tab=w.tabs.currentWidget(); w.show(); self.app.processEvents()
                edit=next(b for b in tab.findChildren(MessageBubble)[0].findChildren(QPushButton) if b.accessibleName()=='Edit and resend prompt')
                edit.click()
                self.assertEqual(tab.composer.toPlainText(),'Original prompt'); self.assertEqual(tab.attachments.paths,[image])
                self.assertEqual(tab.session['messages'],original); request.assert_not_called(); self.assertEqual(store.list_prompts(),[])
                persisted=store.list_sessions()[0]
                self.assertEqual(persisted['draft'],'Original prompt'); self.assertEqual(persisted['draft_images'],[image])
                tab.composer.setPlainText('A different draft')
                with patch('agentnik.ui.confirm',return_value=False) as confirmation:
                    edit.click(); confirmation.assert_called_once()
                self.assertEqual(tab.composer.toPlainText(),'A different draft')
                with patch('agentnik.ui.confirm',return_value=True): edit.click()
                tab.composer.setPlainText('Edited prompt')
                request.return_value={'text':'New answer','thinking':'','metrics':{},'raw':{}}
                result={'text':'New answer','thinking':'','metrics':{},'status':'ok','research':{'status':'completed','route':'managed','sources':[],'events':[],'exchanges':[]}}
                with patch('agentnik.research.run',return_value=result) as managed:
                    tab.submit()
                    deadline=time.monotonic()+3
                    while tab.job and time.monotonic()<deadline: self.app.processEvents(); time.sleep(.01)
                self.assertIsNone(tab.job); managed.assert_called_once()
                wire=core.chat_body(c,managed.call_args.args[1])['messages']
                self.assertEqual([m['role'] for m in wire],['user','assistant','user'])
                self.assertEqual(wire[2]['content'][0]['text'],'Edited prompt')
                self.assertEqual(tab.session['messages'][:2],original)
                self.assertEqual(tab.session['messages'][2]['text'],'Edited prompt')
                self.assertEqual(tab.session['messages'][2]['images'],[image])
                self.assertEqual(len(tab.session['messages']),4)
            finally: w.close(); self.app.processEvents(); store.db.close()

    def test_edit_prompt_is_blocked_while_request_is_running(self):
        from PySide6.QtWidgets import QPushButton
        from agentnik.storage import Store
        from agentnik.ui import Window, MessageBubble
        from agentnik import core
        with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}), patch('agentnik.core.models',return_value=[]):
            store=Store(root); w=Window(store)
            try:
                session=store.new_session('chat','test',{'url':'https://example.com/v1','model':'test'})
                session['messages']=[{'role':'user','text':'Earlier prompt'}]
                w.open_session(session); tab=w.tabs.currentWidget(); w.show(); self.app.processEvents()
                tab.composer.setPlainText('Keep the current draft'); tab.job=object()
                edit=next(b for b in tab.findChildren(MessageBubble)[0].findChildren(QPushButton) if b.accessibleName()=='Edit and resend prompt')
                with patch('agentnik.ui.error') as warning:
                    edit.click(); warning.assert_called_once()
                self.assertEqual(tab.composer.toPlainText(),'Keep the current draft')
            finally: tab.job=None; w.close(); self.app.processEvents(); store.db.close()

    def test_branding_assets_and_font_limits(self):
        from PySide6.QtGui import QImage, QPalette
        from agentnik.storage import Store
        from agentnik.ui import Window
        assets=Path(__file__).resolve().parents[1]/'agentnik'/'assets'
        for name in ('agentnik-light.png','agentnik-dark.png','agentnik-icon.png'):
            image=QImage(str(assets/name)); self.assertFalse(image.isNull()); self.assertTrue(image.hasAlphaChannel()); self.assertEqual(image.pixelColor(0,0).alpha(),0)
            svg=(assets/name).with_suffix('.svg').read_text('utf-8')
            self.assertIn('<path',svg); self.assertNotIn('<image',svg)
        # Qt accepts an SVG as valid even when individual paths are truncated.
        from PySide6.QtCore import qInstallMessageHandler
        from PySide6.QtSvg import QSvgRenderer
        warnings=[]
        def capture(kind,context,message):
            if context.category.startswith('qt.svg'): warnings.append(message)
        previous=qInstallMessageHandler(capture)
        try:
            for svg in [assets.parents[1]/'assets'/'robot.svg',*assets.glob('*.svg')]:
                renderer=QSvgRenderer(str(svg))
                self.assertTrue(renderer.isValid(),str(svg))
        finally: qInstallMessageHandler(previous)
        self.assertEqual(warnings,[])
        with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}):
            store=Store(root); w=Window(store)
            try:
                store.config['settings']['theme']='Light'; w.apply_theme(); self.assertEqual(w.brand_variant,'light'); self.assertFalse(w.brand.pixmap().isNull()); self.assertFalse(w.windowIcon().isNull()); self.assertFalse(w.welcome_brand.pixmap().isNull())
                self.assertGreater(self.app.palette().color(QPalette.ColorRole.Window).lightness(),128)
                store.config['settings']['theme']='Dark'; w.apply_theme(); self.assertEqual(w.brand_variant,'dark')
                self.assertLess(self.app.palette().color(QPalette.ColorRole.Window).lightness(),128)
                w.apply_font_size(8); self.assertFalse(w.font_smaller.isEnabled()); w.font_larger.click(); self.assertEqual(store.config['settings']['font_size'],9)
                w.apply_font_size(32); self.assertFalse(w.font_larger.isEnabled()); w.font_smaller.click(); self.assertEqual(store.config['settings']['font_size'],31)
            finally:
                w.close(); self.app.processEvents(); store.db.close()

    def test_auto_models_refresh_and_chart_button(self):
        from PySide6.QtWidgets import QPushButton, QStackedWidget
        from agentnik.storage import Store
        from agentnik.ui import Window, DecisionResult, ConnectionDialog
        with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}), patch('agentnik.core.models',return_value=['example-model']) as models:
            store=Store(root); w=Window(store)
            try:
                self.assertEqual(ConnectionDialog(w).protocol.currentText(),'responses')
                w.connections={'test':{'url':'http://localhost:11434/v1','protocol':'chat','model':''}}
                w.new_session('chat','test'); tab=w.tabs.currentWidget(); w.show()
                deadline=time.monotonic()+3
                while tab.model.currentText()!='example-model' and time.monotonic()<deadline:
                    self.app.processEvents(); time.sleep(.01)
                self.assertEqual(tab.model.currentText(),'example-model'); self.assertEqual(models.call_count,1)
                tab.models_button.click()
                deadline=time.monotonic()+3
                while models.call_count<2 and time.monotonic()<deadline: self.app.processEvents(); time.sleep(.01)
                self.assertEqual(models.call_count,2)
                chart=DecisionResult({'answers':{'q':{'type':'choice','choice':'a','probabilities':{'a':.8,'b':.2}}}})
                toggle=chart.findChild(QPushButton); stack=chart.findChild(QStackedWidget)
                self.assertEqual(stack.currentIndex(),0); toggle.click(); self.assertEqual(stack.currentIndex(),1); toggle.click(); self.assertEqual(stack.currentIndex(),0)
            finally:
                w.close(); self.app.processEvents(); store.db.close()


    def test_prompts_panel_saves_filters_and_copies_both_types(self):
        from agentnik.storage import Store
        from agentnik.ui import Window, MessageBubble
        from agentnik import core
        with tempfile.TemporaryDirectory() as root, patch('agentnik.core.discover',return_value={}), patch('agentnik.core.environment_connections',return_value={}), patch('agentnik.core.models',return_value=[]), patch('agentnik.ui.confirm',return_value=True), patch('agentnik.ui.QInputDialog.getText',return_value=('',True)):
            store=Store(root); store.config['connections']={'first':{'url':'http://localhost:11434/v1','model':'one'},'second':{'url':'http://localhost:11434/v1','model':'two'}}; w=Window(store)
            try:
                w.new_session('chat','first'); first=w.tabs.currentWidget(); w.show(); self.app.processEvents()
                image=store.attach(data=b'image'); first.composer.setPlainText('Find the truck'); first.attachments.set_paths([image]); first.save_draft(); first.star_current.click()
                self.assertEqual(w.prompts_list.count(),1)
                first.session['messages']=[{'role':'user','text':'Earlier prompt','images':[]}]; first.render()
                historical=first.findChild(MessageBubble).findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton)
                next(b for b in historical if b.accessibleName()=='Save prompt').click()
                self.assertEqual(w.prompts_list.count(),2)
                w.prompts_search.setText('truck'); self.assertEqual(w.prompts_list.count(),1)
                w.new_session('chat','second'); second=w.tabs.currentWidget(); self.app.processEvents()
                w.prompts_list.setCurrentRow(0); w.copy_selected_prompt()
                self.assertEqual(second.composer.toPlainText(),'Find the truck'); self.assertEqual(second.attachments.paths,[image])
                w.prompts_search.clear(); w.tabs.setCurrentWidget(second); self.app.processEvents(); self.assertEqual(w.prompts_list.count(),2)
                w.delete_ids([first.session['id']]); self.assertTrue(Path(image).exists())
                w.toggle_prompts(); self.assertTrue(w.prompts_panel.isHidden()); w.toggle_prompts(); self.assertFalse(w.prompts_panel.isHidden())
            finally:
                w.close(); self.app.processEvents(); store.db.close()

if __name__=='__main__': unittest.main()

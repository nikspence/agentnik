import copy
import unittest
from agentnik.context_compaction import effective_messages,make_snapshot,summary_input
from agentnik.core import chat_body

class ContextCompactionTests(unittest.TestCase):
    def test_preserves_transcript_and_complete_tool_exchanges(self):
        messages=[{'role':'user','text':'earlier'},{'role':'assistant','text':'result','research':{'status':'completed','protocol':'chat','exchanges':[{'role':'assistant','content':'kept exchange'}]}},{'role':'user','text':'recent'},{'role':'assistant','text':'answer'}]
        original=copy.deepcopy(messages);snapshot=make_snapshot(messages,2,'Earlier conclusion')
        effective=effective_messages(messages,snapshot)
        self.assertEqual(messages,original);self.assertEqual(effective[1:],messages[2:]);self.assertIn('Earlier conclusion',effective[0]['text'])
        self.assertEqual(chat_body({'model':'m','protocol':'chat','url':'https://example.test/v1','stream':False},effective)['messages'][-1]['content'],'answer')
    def test_detects_changed_or_invalid_prefix(self):
        messages=[{'role':'user','text':'before'},{'role':'assistant','text':'answer'}];snapshot=make_snapshot(messages,2,'summary')
        messages[0]['text']='changed'
        with self.assertRaises(ValueError):effective_messages(messages,snapshot)
        with self.assertRaises(ValueError):make_snapshot(messages,3,'summary')
        with self.assertRaises(ValueError):make_snapshot(messages,2,'')
        with self.assertRaises(ValueError):make_snapshot(messages,1,'summary')
    def test_summary_input_retains_attachments_and_prior_summary(self):
        messages=[{'role':'user','text':'first','images':['image.png']},{'role':'assistant','text':'reply'},{'role':'user','text':'second'},{'role':'assistant','text':'last'}]
        previous=make_snapshot(messages,2,'prior');inputs=summary_input(messages,4,previous)
        self.assertIn('prior',inputs[0]['text']);self.assertEqual(inputs[1]['text'],'second')
        inputs=summary_input(messages,2);self.assertEqual(inputs[0]['images'],['image.png']);self.assertEqual(messages[0]['images'],['image.png'])

class ChatCompactionUiTests(unittest.TestCase):
    def test_manual_compaction_persists_and_drives_next_request(self):
        import os,tempfile,time
        from unittest.mock import patch
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(directory);store.config['connections']={'test':{'url':'https://example.test/v1','model':'model','protocol':'chat','stream':False}}
            window=Window(store)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget()
                tab.session['messages']=[{'role':'user','text':'Original request'},{'role':'assistant','text':'Original answer'}];store.save(tab.session)
                calls=[]
                def request(connection,mode,body,emit,cancel):
                    calls.append(body)
                    return {'text':'Compact result' if len(calls)==1 else 'Next answer','thinking':'','metrics':{},'raw':{}}
                with patch.object(core,'run_request',side_effect=request):
                    tab.compact_chat_context();deadline=time.monotonic()+3
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    self.assertIsNone(tab.job);self.assertEqual(tab.session['chat_compaction']['summary'],'Compact result')
                    self.assertEqual(tab.session['messages'][0]['text'],'Original request')
                    tab.composer.setPlainText('Next');tab.submit();deadline=time.monotonic()+3
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    self.assertIsNone(tab.job)
                sent=calls[1]['messages'];self.assertIn('Compact result',sent[0]['content']);self.assertNotIn('Original request',str(sent))
                saved=next(s for s in store.list_sessions() if s['id']==tab.session['id']);self.assertEqual(saved['chat_compaction']['summary'],'Compact result')
            finally:window.close();app.processEvents();store.db.close()

    def test_automatic_compaction_runs_before_send(self):
        import os,tempfile,time
        from unittest.mock import patch
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(directory);store.config['connections']={'test':{'url':'https://example.test/v1','model':'model','protocol':'chat','stream':False,'context_limit':100}}
            window=Window(store)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.session['messages']=[{'role':'user','text':'Old '*100},{'role':'assistant','text':'Answer'}]
                tab.composer.setPlainText('New prompt');calls=[]
                def request(connection,mode,body,emit,cancel):
                    calls.append(body);return {'text':'Summary' if len(calls)==1 else 'Final','thinking':'','metrics':{},'raw':{}}
                with patch.object(core,'run_request',side_effect=request):
                    tab.submit();deadline=time.monotonic()+4
                    while (tab.job or len(calls)<2) and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                self.assertEqual(len(calls),2);self.assertIn('Summarize',str(calls[0]));self.assertIn('Summary',str(calls[1]));self.assertNotIn('Old Old',str(calls[1]))
                self.assertEqual(tab.session['messages'][0]['text'],'Old '*100)
            finally:window.close();app.processEvents();store.db.close()

    def test_automatic_failure_does_not_send_prompt_or_replace_history(self):
        import os,tempfile,time
        from unittest.mock import patch
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(directory);store.config['connections']={'test':{'url':'https://example.test/v1','model':'model','protocol':'chat','stream':False,'context_limit':100}}
            window=Window(store)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();history=[{'role':'user','text':'Old '*100},{'role':'assistant','text':'Answer'}];tab.session['messages']=copy.deepcopy(history);tab.composer.setPlainText('Draft')
                with patch.object(core,'run_request',side_effect=ValueError('failed')) as request:
                    tab.submit();deadline=time.monotonic()+3
                    while tab.job and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
                    self.assertEqual(request.call_count,1)
                self.assertEqual(tab.session['messages'],history);self.assertNotIn('chat_compaction',tab.session);self.assertEqual(tab.composer.toPlainText(),'Draft')
            finally:window.close();app.processEvents();store.db.close()

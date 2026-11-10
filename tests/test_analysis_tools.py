"""Offline numeric contracts and tool loops; never calls a live endpoint."""
import copy
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentnik import core,research
from agentnik.analysis_tools import calculate,analyze_data,AnalysisError
from agentnik.tools import Registry,Runtime,Limits,ToolCall,ResearchError
from agentnik.code_agent import CodingRun
from test_compat_tools import chat,msg
from test_code_agent import C,call
from test_routing import Wire
from test_research import answer,Response,call as native_call

DATA=json.dumps({'format':'csv','content':'team,amount\na,10\na,20\nb,\nb,no\nb,30','group_by':'team'})


class AnalysisTools(unittest.TestCase):
    def test_arithmetic_and_bounded_language(self):
        self.assertEqual(calculate('(2+3)*4**2')['value'],80)
        self.assertEqual(calculate('round(sqrt(81) + pi, 2)')['value'],12.14)
        self.assertEqual(calculate('10 % 3 + 7 // 2')['value'],4)
        for expression in ('__import__("os")','open("secret")','(1).__class__','[1,2]','True','2**101','10**1000','1/0','sqrt(-1)','1e309','sum(x for x in [1])','abs(x=1)','(-1)**0.5'):
            with self.subTest(expression=expression),self.assertRaises(AnalysisError):calculate(expression)

    def test_csv_and_json_statistics_missing_and_groups(self):
        result=analyze_data(DATA);column=result['columns']['amount']
        self.assertEqual(result['rows'],5);self.assertEqual(column['mean'],20);self.assertEqual(column['sample_stdev'],10)
        self.assertEqual(column['missing_count'],1);self.assertEqual(column['nonnumeric_count'],1)
        self.assertEqual(result['groups'][0]['value'],'a');self.assertEqual(result['groups'][0]['columns']['amount']['sum'],30)
        request=json.dumps({'format':'json','content':json.dumps([{'x':1,'b':True},{'x':3},{'x':None},{'x':'NaN'}])})
        result=analyze_data(request);self.assertEqual(result['columns']['x']['median'],2);self.assertEqual(result['columns']['x']['nonnumeric_count'],1);self.assertEqual(result['columns']['b']['numeric_count'],0)

    def test_bad_shapes_limits_and_malformed_rows(self):
        for data in ('{}','[]',json.dumps({'format':'csv','content':'x,x\n1,2'}),json.dumps({'format':'csv','content':'x,y\n1'}),json.dumps({'format':'json','content':'[{"x":[]}]'}),json.dumps({'format':'csv','content':'x\n'+'1\n'*1001}),json.dumps({'format':'csv','content':'x\n'+'\n'.join(str(i) for i in range(11)),'group_by':'x'})):
            with self.subTest(data=data[:80]),self.assertRaises(AnalysisError):analyze_data(data)

    def test_registry_opt_in_and_recoverable_errors(self):
        registry=Registry(None,None,local_tools=True,web_tools=False)
        self.assertEqual(set(registry.definitions),{'calculate','analyze_data'})
        with self.assertRaises(ResearchError):registry.validate(ToolCall('w','web_fetch',{'url':'https://example.org'}),Limits())
        result=registry.execute(ToolCall('c','calculate',{'expression':'1/0'}),Runtime())
        self.assertTrue(result.error);self.assertIsNone(result.data)
        with self.assertRaises(ResearchError):Registry(None,None).validate(ToolCall('c','calculate',{'expression':'2+2'}),Limits())

    def test_local_chat_loop_no_web_and_result_continuation(self):
        bodies=[];replies=[Wire(chat(calls=[call('calculate',{'expression':'6*7'}),call('analyze_data',{'data':DATA},'data')],finish='tool_calls'),False),Wire(chat('42; mean 20'),False)]
        def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send),patch('agentnik.web.OllamaWeb.search',side_effect=AssertionError('No web')),patch('agentnik.web.OllamaWeb.fetch',side_effect=AssertionError('No web')):
            result=research.run({'url':'https://example.org/v1','model':'test','protocol':'chat','stream':False},[{'role':'user','text':'Calculate'}],'',lambda _:None,threading.Event(),config={'local_tools':True,'web_enabled':False})
        self.assertEqual(result['status'],'ok');self.assertTrue(result['research']['local_only']);self.assertEqual(result['research']['capability_updates'],[])
        self.assertEqual({t['function']['name'] for t in bodies[0]['tools']},{'calculate','analyze_data'})
        results=[json.loads(m['content']) for m in bodies[1]['messages'] if m['role']=='tool']
        self.assertEqual(results[0]['data']['value'],42);self.assertEqual(results[1]['data']['rows'],5)

    def test_messages_responses_and_native_continuation(self):
        variants=[('messages',[Wire(msg([{'type':'tool_use','id':'a','name':'calculate','input':{'expression':'2+2'}}],'tool_use'),False),Wire(msg([{'type':'text','text':'4'}]),False)]),('responses',[Wire({'output':[{'type':'function_call','call_id':'a','name':'calculate','arguments':'{"expression":"2+2"}'}],'status':'completed'},False),Wire({'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'4'}]}],'status':'completed'},False)]),('native',[Response([answer(calls=[native_call('calculate',{'expression':'2+2'})])],False),Response([answer('4')],False)])]
        for protocol,replies in variants:
            c={'url':'http://localhost:11434/v1' if protocol=='native' else 'https://example.org/v1','model':'test','protocol':'chat' if protocol=='native' else protocol,'stream':False}
            with self.subTest(protocol=protocol),patch.object(core,'open_request',side_effect=replies):
                result=research.run_managed(c,[{'role':'user','text':'Calculate'}],'',lambda _:None,threading.Event(),local_tools=True,web_tools=False)
                self.assertEqual(result['status'],'ok',result.get('error'));self.assertEqual(result['text'],'4')

    def test_code_tools_without_research_or_approval(self):
        with tempfile.TemporaryDirectory() as root:
            events=[];bodies=[];replies=[Wire(chat(calls=[call('calculate',{'expression':'9*9'}),call('analyze_data',{'data':DATA},'d')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send),patch('subprocess.Popen',side_effect=AssertionError('No shell')):CodingRun(dict(C,stream=False),root,'Calculate').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertFalse(any(e['kind'] in ('operation_proposal','edit_proposal') for e in events))
            results=[json.loads(m['content']) for m in bodies[1]['messages'] if m['role']=='tool'];self.assertEqual(results[0]['value'],81);self.assertEqual(results[1]['rows'],5)


class AnalysisUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_local_opt_in_persists_without_enabling_web(self):
        from agentnik.storage import Store
        from agentnik.ui import Window
        with tempfile.TemporaryDirectory() as root,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}),patch('agentnik.core.models',return_value=[]):
            store=Store(root);store.config['connections']={'local':{'url':'http://localhost:11434/v1','model':'test'}};window=Window(store)
            try:
                window.new_session('chat','local');tab=window.tabs.currentWidget()
                self.assertFalse(tab.local_tools.isChecked());self.assertFalse(tab.web_access.isChecked())
                tab.local_tools.setChecked(True);session=next(s for s in store.list_sessions() if s['id']==tab.session['id'])
                self.assertTrue(session['research_options']['local_tools']);self.assertFalse(session['research_options']['enabled'])
                tab.busy(True);self.assertFalse(tab.local_tools.isEnabled());tab.busy(False);self.assertTrue(tab.local_tools.isEnabled())
                from agentnik.ui import SessionTab
                reopened=SessionTab(window,session);self.assertTrue(reopened.local_tools.isChecked());self.assertFalse(reopened.web_access.isChecked());reopened._closed=True;reopened.close()
            finally:window.close();self.app.processEvents();store.db.close()

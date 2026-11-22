import unittest
import sys
import threading
import tempfile
from pathlib import Path
from PySide6.QtCore import QEventLoop,QTimer,QObject,Signal
from PySide6.QtWidgets import QApplication
from agentnik.mcp_elicitation import ElicitationDialog,parse_input_required,continuation


def request():
    return {'resultType':'input_required','requestState':'opaque-state','inputRequests':{'item':{'method':'elicitation/create','params':{'mode':'form','message':'Choose a format','requestedSchema':{'type':'object','properties':{'format':{'type':'string','enum':['csv','json'],'enumNames':['CSV','JSON'],'default':'csv'}},'required':['format']}}}}}


class ElicitationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_parse_and_review_valid_answer(self):
        parsed=parse_input_required(request());self.assertEqual(parsed['request_state'],'opaque-state')
        dialog=ElicitationDialog('Example',parsed['forms']);self.assertIn('csv',dialog.answer.toPlainText())
        dialog.answer.setPlainText('{"format":"unknown"}');dialog.submit();self.assertTrue(dialog.error.text());self.assertEqual(dialog.responses,{})
        dialog.answer.setPlainText('{"format":"json"}');dialog.submit();self.assertEqual(dialog.responses,{'item':{'action':'accept','content':{'format':'json'}}});self.assertEqual(dialog.result(),QDialogAccepted)

    def test_decline_and_unsupported_requests(self):
        parsed=parse_input_required(request());dialog=ElicitationDialog('Example',parsed['forms']);dialog.decline();self.assertEqual(dialog.responses,{'item':{'action':'decline'}})
        for change in ('url','unknown','invalid_schema'):
            value=request();params=value['inputRequests']['item']['params']
            if change=='url':params['mode']='url'
            elif change=='unknown':value['inputRequests']['item']['method']='sampling/createMessage'
            else:params['requestedSchema']={'type':'object','properties':{'x':{'$ref':'https://invalid.example/schema'}}}
            with self.subTest(change=change),self.assertRaises(ValueError):parse_input_required(value)

    def test_continuation_requires_every_valid_answer_and_preserves_state(self):
        data=request();data['inputRequests']['second']=data['inputRequests']['item'].copy();pending=parse_input_required(data)
        original={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'work','arguments':{}}}
        with self.assertRaises(ValueError):continuation(original,pending,{'item':{'action':'decline'}})
        responses={'item':{'action':'accept','content':{'format':'csv'}},'second':{'action':'decline'}}
        result=continuation(original,pending,responses);self.assertEqual(result['params']['requestState'],'opaque-state');self.assertEqual(result['params']['inputResponses'],responses);self.assertNotIn('inputResponses',original['params'])

    def test_form_format_is_checked_without_echoing_private_value(self):
        value=request();value['inputRequests']['item']['params']['requestedSchema']={'type':'object','properties':{'address':{'type':'string','format':'email'}},'required':['address']}
        dialog=ElicitationDialog('Example',parse_input_required(value)['forms']);dialog.answer.setPlainText('{"address":"private-invalid"}');dialog.submit()
        self.assertTrue(dialog.error.text());self.assertNotIn('private-invalid',dialog.error.text());self.assertEqual(dialog.responses,{})

    def test_bridge_opens_dialog_and_continues_only_after_answer(self):
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        server_path=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py'
        server={'name':'Example','command':sys.executable,'args':['-u',str(server_path)],'enabled':True}
        bridge=CodingMCPBridge(server,{'mcp_servers':[server]});runtime=Runtime(threading.Event(),Limits());out=[];presented=[]
        def worker():
            info=bridge.request('discover',{},runtime);out.append(info)
            out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{'text':'input'}},runtime))
            bridge.close_signal.emit()
        thread=threading.Thread(target=worker);thread.start();loop=QEventLoop();poll=QTimer()
        def tick():
            dialog=bridge.elicitation_dialog
            if dialog and not presented:
                presented.append(dialog.message.text());self.assertEqual(len(out),1)
                dialog.answer.setPlainText('{"choice":"yes"}');dialog.submit()
            if not thread.is_alive():loop.quit()
        poll.timeout.connect(tick);poll.start(10);QTimer.singleShot(7000,loop.quit);loop.exec();poll.stop();thread.join(1);self.app.processEvents()
        self.assertFalse(thread.is_alive());self.assertEqual(presented,['private-server-text']);self.assertEqual(out[1]['call_result']['content'][0]['text'],'continued');self.assertNotIn('private-state',str(out))

    def test_dialog_cancellation_stops_call_without_continuing(self):
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        server_path=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py';server={'name':'Example','command':sys.executable,'args':['-u',str(server_path)],'enabled':True}
        bridge=CodingMCPBridge(server,{'mcp_servers':[server]});runtime=Runtime(threading.Event(),Limits());out=[];cancelled=[]
        def worker():
            info=bridge.request('discover',{},runtime)
            out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{'text':'input'}},runtime));bridge.close_signal.emit()
        thread=threading.Thread(target=worker);thread.start();loop=QEventLoop();poll=QTimer()
        def tick():
            dialog=bridge.elicitation_dialog
            if dialog and not cancelled:cancelled.append(True);dialog.reject()
            if not thread.is_alive():loop.quit()
        poll.timeout.connect(tick);poll.start(10);QTimer.singleShot(7000,loop.quit);loop.exec();poll.stop();thread.join(1);self.app.processEvents()
        self.assertFalse(thread.is_alive());self.assertTrue(cancelled);self.assertTrue(out[0]['call_uncertain']);self.assertIn('cancelled',out[0]['error']);self.assertNotIn('private-state',str(out))

    def test_decline_is_sent_to_server_as_explicit_response(self):
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        server_path=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py';server={'name':'Example','command':sys.executable,'args':['-u',str(server_path)],'enabled':True}
        bridge=CodingMCPBridge(server,{'mcp_servers':[server]});runtime=Runtime(threading.Event(),Limits());out=[];declined=[]
        def worker():
            info=bridge.request('discover',{},runtime);out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{'text':'input'}},runtime));bridge.close_signal.emit()
        thread=threading.Thread(target=worker);thread.start();loop=QEventLoop();poll=QTimer()
        def tick():
            dialog=bridge.elicitation_dialog
            if dialog and not declined:declined.append(True);dialog.decline()
            if not thread.is_alive():loop.quit()
        poll.timeout.connect(tick);poll.start(10);QTimer.singleShot(7000,loop.quit);loop.exec();poll.stop();thread.join(1);self.app.processEvents()
        self.assertFalse(thread.is_alive());self.assertTrue(declined);self.assertEqual(out[0]['call_result']['content'][0]['text'],'declined')

    def test_stopping_run_closes_dialog_without_continuation(self):
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        server_path=Path(__file__).parent/'fixtures'/'mcp_modern_stdio.py';server={'name':'Example','command':sys.executable,'args':['-u',str(server_path)],'enabled':True}
        bridge=CodingMCPBridge(server,{'mcp_servers':[server]});runtime=Runtime(threading.Event(),Limits());out=[];stopped=[]
        def worker():
            info=bridge.request('discover',{},runtime);out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{'text':'input'}},runtime))
        thread=threading.Thread(target=worker);thread.start();loop=QEventLoop();poll=QTimer()
        def tick():
            if bridge.elicitation_dialog and not stopped:stopped.append(True);bridge.close_signal.emit()
            if not thread.is_alive():loop.quit()
        poll.timeout.connect(tick);poll.start(10);QTimer.singleShot(7000,loop.quit);loop.exec();poll.stop();thread.join(1);self.app.processEvents()
        self.assertFalse(thread.is_alive());self.assertTrue(stopped);self.assertTrue(out[0]['call_uncertain']);self.assertIsNone(bridge.elicitation_dialog)

    def test_server_manager_can_answer_manual_tool_request(self):
        from unittest.mock import patch
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        class Session(QObject):
            elicitation_requested=Signal(object)
            def __init__(self):super().__init__();self.received=None;self.elicitation_enabled=False
            def continue_elicitation(self,value):self.received=value
            def close(self):pass
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(folder);window=Window(store);manager=MCPServers(window);session=Session();manager.process=session;manager.attach_elicitation(session,'Example')
            try:
                session.elicitation_requested.emit(parse_input_required(request())['forms']);self.assertTrue(session.elicitation_enabled)
                manager.elicitation_dialog.answer.setPlainText('{"format":"json"}');manager.elicitation_dialog.submit();self.assertEqual(session.received['item']['content'],{'format':'json'})
            finally:manager.close();window.close();self.app.processEvents();store.db.close()


from PySide6.QtWidgets import QDialog
QDialogAccepted=QDialog.DialogCode.Accepted

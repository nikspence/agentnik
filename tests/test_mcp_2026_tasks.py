import unittest

from agentnik.mcp_2026 import PROTOCOL,parse_discovery,prepare_request
from agentnik.mcp_2026_tasks import TaskTracker


def task(status='working',result_type='complete',**extra):
    return dict({'resultType':result_type,'taskId':'synthetic-task','status':status,'createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttlMs':None,'pollIntervalMs':200},**extra)


def input_request(message='Choose'):
    return {'method':'elicitation/create','params':{'message':message,'requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}}


class ModernTaskProtocolTests(unittest.TestCase):
    def test_capability_is_reported_without_claiming_execution(self):
        value={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{},'extensions':{'io.modelcontextprotocol/tasks':{}}}}
        result=parse_discovery(value);self.assertTrue(result['task_extension_advertised']);self.assertFalse(result['task_capabilities']['tool_calls'])
        for extensions in (None,[],{'io.modelcontextprotocol/tasks':None},{}):
            value['capabilities']['extensions']=extensions;self.assertFalse(parse_discovery(value)['task_extension_advertised'])

    def test_empty_mrtr_input_is_valid_but_missing_fields_are_not(self):
        from agentnik.mcp_elicitation import parse_input_required,continuation
        pending=parse_input_required({'resultType':'input_required','inputRequests':{}})
        self.assertEqual(pending['forms'],[])
        message=continuation({'method':'tools/call','params':{'name':'work'}},pending,{})
        self.assertEqual(message['params'],{'name':'work','inputResponses':{}})
        for value in ({'resultType':'input_required'},{'resultType':'input_required','inputRequests':None},{'resultType':'input_required','requestState':None}):
            with self.subTest(value=value),self.assertRaises(ValueError):parse_input_required(value)

    def test_server_manager_discloses_unavailable_modern_tasks(self):
        import tempfile
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(folder);window=Window(store);manager=MCPServers(window)
            try:
                manager.discovered_config={};manager.remote_done({'name':'Example','version':'1','protocol':PROTOCOL,'tools':[],'tool_details':[],'task_extension_advertised':True,'task_capabilities':{'tool_calls':False}})
                self.assertIn('cannot execute',manager.tool_details.toPlainText());self.assertFalse(manager.discovered['task_capabilities']['tool_calls'])
            finally:manager.close();window.close();app.processEvents();store.db.close()

    def test_chat_discovery_discloses_unavailable_modern_tasks(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication
        from agentnik.chat_mcp import MultiChatMCP
        from agentnik.tools import Runtime
        app=QApplication.instance() or QApplication([])
        servers=[{'name':name,'command':'example','args':[],'enabled':True} for name in ('Example','Second')];group=MultiChatMCP(servers,{'mcp_servers':servers})
        group.controllers[0].bridge=Mock();group.controllers[0].bridge.request.return_value={'tool_details':[],'task_extension_advertised':True,'task_capabilities':{'tool_calls':False}}
        group.controllers[1].bridge=Mock();group.controllers[1].bridge.request.return_value={'tool_details':[]}
        result=group.invoke('mcp_discover',{'server':'connect'},Runtime());notice=result['server_capabilities'][0]['task_extension_notice']
        self.assertIn('does not yet support',notice);self.assertFalse(result['server_capabilities'][0]['task_capabilities']['tool_calls'])

    def test_task_requests_use_required_routing_header(self):
        tracker=TaskTracker(task(result_type='task'))
        for method in ('tasks/get','tasks/cancel'):
            request,headers=prepare_request(tracker.request(method,4));self.assertEqual(headers['Mcp-Method'],method);self.assertEqual(headers['Mcp-Name'],'synthetic-task');self.assertEqual(request['params']['taskId'],'synthetic-task')
        with self.assertRaises(ValueError):prepare_request({'jsonrpc':'2.0','id':1,'method':'tasks/update','params':{'inputResponses':{}}})
        _,headers=prepare_request({'jsonrpc':'2.0','id':2,'method':'tasks/get','params':{'taskId':' task\n'}})
        self.assertTrue(headers['Mcp-Name'].startswith('=?base64?'))

    def test_poll_input_update_deduplicates_and_delivers_result(self):
        tracker=TaskTracker(task(result_type='task'));self.assertEqual(tracker.observe(task())['delay_ms'],200)
        first=tracker.observe(task('input_required',inputRequests={'one':input_request()}));self.assertEqual(first['action'],'input')
        with self.assertRaises(ValueError):tracker.request('tasks/get')
        response={'one':{'action':'accept','content':{'choice':'yes'}}};update=tracker.respond(response,7)
        response['one']['content']['choice']='changed';self.assertEqual(update['params']['inputResponses']['one']['content']['choice'],'yes')
        _,headers=prepare_request(update);self.assertEqual(headers['Mcp-Name'],'synthetic-task')
        with self.assertRaises(ValueError):tracker.request('tasks/get')
        with self.assertRaises(ValueError):tracker.observe(task())
        self.assertEqual(tracker.request('tasks/cancel')['method'],'tasks/cancel');tracker.acknowledge({'resultType':'complete'})
        with self.assertRaises(ValueError):tracker.respond(response)
        self.assertEqual(tracker.observe(task('input_required',inputRequests={'one':input_request()}))['action'],'poll')
        second=tracker.observe(task('input_required',inputRequests={'one':input_request(),'two':input_request('Another')}));self.assertEqual([form['id'] for form in second['forms']],['two'])
        tracker.respond({'two':{'action':'decline'}});tracker.acknowledge({'resultType':'complete'})
        complete=tracker.observe(task('completed',result={'content':[{'type':'text','text':'done'}]}));self.assertEqual(complete['result']['content'][0]['text'],'done')
        with self.assertRaises(ValueError):tracker.request('tasks/get')

    def test_task_rejects_changed_request_and_invalid_shapes(self):
        tracker=TaskTracker(task(result_type='task'));tracker.observe(task('input_required',inputRequests={'one':input_request()}));tracker.respond({'one':{'action':'decline'}});tracker.acknowledge({'resultType':'complete'})
        with self.assertRaises(ValueError):tracker.observe(task('input_required',inputRequests={'one':input_request('Changed')}))
        for changes in ({'taskId':'other'}, {'status':[]}, {'ttlMs':True}, {'pollIntervalMs':-1}, {'lastUpdatedAt':'bad'}, {'resultType':'task'}, {'status':'completed','result':[]}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                value=task();value.update(changes);TaskTracker(task(result_type='task')).observe(value)
        for ack in ({},{'resultType':'complete','unexpected':1},{'resultType':'task'}):
            with self.subTest(ack=ack),self.assertRaises(ValueError):TaskTracker(task(result_type='task')).acknowledge(ack)
        with self.assertRaises(ValueError):TaskTracker(task(result_type='task')).observe(task('input_required',inputRequests={}))

    def test_failures_are_bounded_and_cancellation_ack_is_not_completion(self):
        tracker=TaskTracker(task(result_type='task'));failed=tracker.observe(task('failed',error={'code':-32603,'message':'problem','data':{'private':'secret'}}))
        self.assertEqual(failed['action'],'failed');self.assertNotIn('secret',str(failed))
        tracker=TaskTracker(task(result_type='task'));tracker.acknowledge({'resultType':'complete'},method='tasks/cancel');self.assertFalse(tracker.terminal)
        self.assertEqual(tracker.observe(task('cancelled'))['action'],'cancelled')

    def test_modern_cancel_cleanup_never_discloses_task_identifier_or_claims_stop(self):
        from agentnik.mcp_support import task_cleanup_text
        for accepted in (True,False):
            text=task_cleanup_text({'server':'Example','modern_task_cancel_ack':accepted})
            self.assertIn('may still be running',text);self.assertNotIn('synthetic-task',text)


if __name__=='__main__':unittest.main()

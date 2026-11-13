"""Context usage estimates and coding-agent tool behavior."""
import json
import tempfile
import unittest
from unittest.mock import patch
from agentnik.context_usage import request_measurement,context_usage
from agentnik.tools import Runtime,Limits
from agentnik.code_agent import CodingRun
from test_code_agent import C,call
from test_compat_tools import chat,msg
from test_routing import Wire,response,message

class ContextUsage(unittest.TestCase):
    def test_content_free_measurement_and_unknown_values(self):
        body={'model':'secret-model','messages':[{'role':'system','content':'private-instructions'},{'role':'user','content':'user-private'},{'role':'tool','content':'private-result'}],'tools':[{'name':'tool'}]}
        result=request_measurement(body)
        self.assertEqual(result['json_bytes'],len(json.dumps(body).encode()))
        self.assertNotIn('private',json.dumps(result));self.assertEqual(result['largest_components'][0]['category'],'instructions')
        runtime=Runtime(limits=Limits());usage=context_usage(runtime,runtime.limits,{},0,result,None)
        self.assertIsNone(usage['last_heavy_request']['configured_context_limit_tokens']);self.assertIsNone(usage['last_heavy_request']['reported_input_tokens'])
        self.assertIn('not tokens',usage['notice'])

    def test_chat_responses_and_messages_protocols(self):
        cases=[
            ('chat',[chat(calls=[call('get_context_usage',{})],finish='tool_calls'),chat('Done')]),
            ('responses',[response([{'type':'function_call','id':'fc-1','call_id':'call-1','name':'get_context_usage','arguments':'{}','status':'completed'}]),response([message('Done')])]),
            ('messages',[msg([{'type':'tool_use','id':'call-1','name':'get_context_usage','input':{}}],'tool_use'),msg([{'type':'text','text':'Done'}])])]
        for protocol,replies in cases:
            with self.subTest(protocol=protocol),tempfile.TemporaryDirectory() as directory:
                bodies=[];events=[];wires=[Wire(reply,False) for reply in replies]
                def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return wires.pop(0)
                with patch('agentnik.core.open_request',side_effect=request):CodingRun(dict(C,protocol=protocol,stream=False,context_limit=8192),directory,'private-task').run(events.append)
                self.assertEqual(events[-1]['status'],'completed')
                if protocol=='responses':content=next(x['output'] for x in bodies[1]['input'] if x.get('type')=='function_call_output')
                elif protocol=='messages':content=bodies[1]['messages'][-1]['content'][0]['content']
                else:content=next(x['content'] for x in bodies[1]['messages'] if x.get('role')=='tool')
                value=json.loads(content);last=value['last_heavy_request'];budget=value['run_budget']
                self.assertEqual(last['json_bytes'],len(json.dumps(bodies[0]).encode()));self.assertEqual(last['reported_input_tokens'],10);self.assertEqual(last['configured_context_limit_tokens'],8192)
                self.assertEqual(budget['model_requests_used'],1);self.assertEqual(budget['tool_calls_used'],1);self.assertEqual(budget['current_tool_round'],1);self.assertGreater(budget['charged_context_bytes'],0)
                self.assertNotIn('private-task',content);self.assertTrue(last['largest_components'])

    def test_no_usage_response_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            first=chat(calls=[call('get_context_usage',{})],finish='tool_calls');first.pop('usage')
            wires=[Wire(first,False),Wire(chat('Done'),False)];bodies=[];events=[]
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return wires.pop(0)
            with patch('agentnik.core.open_request',side_effect=request):CodingRun(dict(C,stream=False),directory,'Task').run(events.append)
            output=json.loads(next(m['content'] for m in bodies[1]['messages'] if m.get('role')=='tool'))
            self.assertIsNone(output['last_heavy_request']['reported_input_tokens']);self.assertIsNone(output['last_heavy_request']['configured_context_limit_tokens'])

    def test_native_ollama_tool_report(self):
        from test_research import Response,answer,call as native_call
        with tempfile.TemporaryDirectory() as directory:
            tool=native_call('get_context_usage',{'placeholder':'value'});tool['function']['arguments']={}
            replies=[Response([answer('',[tool])]),Response([answer('Done')])];bodies=[];events=[]
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.core.open_request',side_effect=request):CodingRun(dict(C,url='http://localhost:11434/v1',protocol='chat',stream=False),directory,'Task').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');value=json.loads(next(item['content'] for item in bodies[1]['messages'] if item.get('role')=='tool'))
            self.assertEqual(value['run_budget']['tool_calls_used'],1);self.assertEqual(value['last_heavy_request']['json_bytes'],len(json.dumps(bodies[0]).encode()))

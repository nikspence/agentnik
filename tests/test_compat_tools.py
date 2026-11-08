"""Offline D protocol matrix: Chat Completions and Messages continuation."""
import copy,json,threading,unittest
from unittest.mock import patch
from agentnik import core,research
from test_research import Backend,MESSAGES
from test_routing import Wire


def chat_call(ident='call-1',args='{"query":"evidence"}'):
    return {'id':ident,'type':'function','function':{'name':'web_search','arguments':args}}


def chat(text='',calls=None,finish='stop'):
    return {'choices':[{'message':{'role':'assistant','content':text,**({'tool_calls':calls} if calls else {})},'finish_reason':finish}],
            'usage':{'prompt_tokens':10,'completion_tokens':3}}


def msg(content,stop='end_turn'):
    return {'type':'message','role':'assistant','content':content,'stop_reason':stop,'usage':{'input_tokens':10,'output_tokens':3}}


class Matrix(unittest.TestCase):
    def run_loop(self,protocol,replies,stream=False):
        c={'url':'https://example.com/v1','protocol':protocol,'model':'test','stream':stream}
        bodies=[]; backend=Backend()
        def send(c,url,body,timeout): bodies.append(copy.deepcopy(body)); return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):
            result=research.run_managed(c,MESSAGES,'web-key',lambda _:None,threading.Event(),backend=backend)
        return result,bodies,backend,c

    def test_chat_multiple_calls_results_and_followup_history(self):
        result,bodies,backend,c=self.run_loop('chat',[Wire(chat(calls=[chat_call(),chat_call('call-2')],finish='tool_calls'),False),Wire(chat('Answer [S1] [S2]'),False)])
        self.assertEqual(result['status'],'ok'); self.assertEqual(len(backend.searches),2)
        self.assertEqual([m['tool_call_id'] for m in bodies[1]['messages'] if m['role']=='tool'],['call-1','call-2'])
        self.assertTrue(all('tool_name' not in m for m in bodies[1]['messages']))
        self.assertEqual(result['metrics']['input_tokens'],20)
        follow=core.chat_body(c,MESSAGES+[dict(role='assistant',**result)])
        self.assertEqual(follow['messages'][-4:],result['research']['exchanges'])

    def test_chat_stream_assembles_arguments_and_reads_usage_after_finish(self):
        events=[{'choices':[{'delta':{'tool_calls':[dict(chat_call(args='{"que'),index=0)]}}]},
                {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'ry":"evidence"}'}}]},'finish_reason':'tool_calls'}]},
                {'choices':[],'usage':{'prompt_tokens':12,'completion_tokens':4}}]
        result,bodies,backend,c=self.run_loop('chat',[Wire(events),Wire([{'choices':[{'delta':{'content':'Answer [S1]'},'finish_reason':'stop'}],'usage':{'prompt_tokens':8,'completion_tokens':2}}])],True)
        self.assertEqual(result['status'],'ok'); self.assertEqual(backend.searches,['evidence']); self.assertEqual(result['metrics']['input_tokens'],20)

    def test_messages_preserve_signed_and_redacted_thinking_and_group_results(self):
        thinking={'type':'thinking','thinking':'Plan','signature':'opaque-signature'}
        redacted={'type':'redacted_thinking','data':'opaque-redacted'}
        calls=[{'type':'tool_use','id':ident,'name':'web_search','input':{'query':'evidence'}} for ident in ('a','b')]
        result,bodies,backend,c=self.run_loop('messages',[Wire(msg([thinking,redacted,*calls],'tool_use'),False),Wire(msg([{'type':'text','text':'Answer [S1] [S2]'}]),False)])
        self.assertEqual(result['status'],'ok'); self.assertEqual(len(backend.searches),2)
        self.assertEqual(bodies[1]['messages'][-2]['content'][:2],[thinking,redacted])
        self.assertEqual([b['tool_use_id'] for b in bodies[1]['messages'][-1]['content']],['a','b'])
        self.assertEqual(bodies[1]['messages'][-1]['role'],'user'); self.assertIn('system',bodies[1])
        follow=core.chat_body(c,MESSAGES+[dict(role='assistant',**result)])
        self.assertEqual(follow['messages'][-3:],result['research']['exchanges'])

    def test_messages_stream_json_thinking_and_signature(self):
        events=[{'type':'message_start','message':{'usage':{'input_tokens':12}}},
                {'type':'content_block_start','index':0,'content_block':{'type':'thinking','thinking':'','signature':''}},
                {'type':'content_block_delta','index':0,'delta':{'type':'thinking_delta','thinking':'Plan'}},
                {'type':'content_block_delta','index':0,'delta':{'type':'signature_delta','signature':'signed'}},
                {'type':'content_block_stop','index':0},
                {'type':'content_block_start','index':1,'content_block':{'type':'tool_use','id':'a','name':'web_search','input':{}}},
                {'type':'content_block_delta','index':1,'delta':{'type':'input_json_delta','partial_json':'{"query":'}},
                {'type':'content_block_delta','index':1,'delta':{'type':'input_json_delta','partial_json':'"evidence"}'}},
                {'type':'content_block_stop','index':1},
                {'type':'message_delta','delta':{'stop_reason':'tool_use'},'usage':{'output_tokens':4}}, {'type':'message_stop'}]
        final=[{'type':'message_start','message':{}}, {'type':'content_block_start','index':0,'content_block':{'type':'text','text':'Answer [S1]'}}, {'type':'content_block_stop','index':0},
               {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':2}}, {'type':'message_stop'}]
        result,bodies,backend,c=self.run_loop('messages',[Wire(events),Wire(final)],True)
        self.assertEqual(result['status'],'ok'); self.assertEqual(bodies[1]['messages'][-2]['content'][0]['signature'],'signed')
        self.assertFalse(result['metrics']['usage_complete'])

    def test_malformed_duplicate_unknown_and_truncated_calls_never_execute(self):
        for calls in ([chat_call(args='{bad')],[chat_call(),chat_call()], [dict(chat_call(),function={'name':'shell','arguments':'{}'})]):
            result,_,backend,_=self.run_loop('chat',[Wire(chat(calls=calls,finish='tool_calls'),False)])
            self.assertEqual(result['status'],'failed'); self.assertFalse(backend.searches)
        for stop in ('max_tokens',None):
            result,_,backend,_=self.run_loop('messages',[Wire(msg([{'type':'tool_use','id':'a','name':'web_search','input':{'query':'x'}}],stop),False)])
            self.assertEqual(result['status'],'failed'); self.assertFalse(backend.searches)

    def test_messages_invalid_lifecycle_never_executes(self):
        start={'type':'message_start','message':{}}
        block={'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'a','name':'web_search','input':{'query':'evidence'}}}
        close={'type':'content_block_stop','index':0}
        delta={'type':'message_delta','delta':{'stop_reason':'tool_use'}}
        stop={'type':'message_stop'}
        valid=[start,block,close,delta,stop]
        fixtures=[valid[1:], [start,*valid], valid+[stop], valid+[block],
                  [start,block,delta,close,stop], [start,block,close,stop],
                  [start,block,close,delta,delta,stop],
                  [start,block,close,delta,block,stop],
                  [start,block,close,{'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':'{}'}},delta,stop]]
        for events in fixtures:
            with self.subTest(events=events):
                result,_,backend,_=self.run_loop('messages',[Wire(events)],True)
                self.assertEqual(result['status'],'failed'); self.assertFalse(backend.searches)

    def test_chat_stream_multiple_fragmented_calls_preserve_correlation(self):
        events=[{'choices':[{'delta':{'tool_calls':[
                    {'index':0,'id':'first','type':'function','function':{'name':'web_','arguments':'{"query":'}},
                    {'index':1,'id':'second','type':'function','function':{'name':'web_search','arguments':'{"query":"two"}'}}]}}]},
                {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'search','arguments':'"one"}'}}]},'finish_reason':'tool_calls'}]}]
        final=[{'choices':[{'delta':{'content':'Answer [S1] [S2]'},'finish_reason':'stop'}]}]
        result,bodies,backend,_=self.run_loop('chat',[Wire(events),Wire(final)],True)
        self.assertEqual(result['status'],'ok'); self.assertEqual(backend.searches,['one','two'])
        self.assertEqual([m['tool_call_id'] for m in bodies[1]['messages'] if m['role']=='tool'],['first','second'])

    def test_chat_invalid_fragments_and_terminal_events_never_execute(self):
        call=dict(chat_call(),index=0)
        end={'choices':[{'delta':{},'finish_reason':'tool_calls'}]}
        first={'choices':[{'delta':{'tool_calls':[call]}}]}
        fixtures=[[first,end,end], [first,end,first],
                  [{'choices':[{'delta':{'tool_calls':[chat_call()]},'finish_reason':'tool_calls'}]}],
                  [{'choices':[{'delta':{'tool_calls':[call,call]},'finish_reason':'tool_calls'}]}]]
        for bad in [dict(call,id=42),dict(call,function=[]),dict(call,function={'name':'web_search','arguments':{}})]:
            fixtures.append([{'choices':[{'delta':{'tool_calls':[bad]},'finish_reason':'tool_calls'}]}])
        for events in fixtures:
            with self.subTest(events=events):
                result,_,backend,_=self.run_loop('chat',[Wire(events)],True)
                self.assertEqual(result['status'],'failed'); self.assertFalse(backend.searches)

    def test_disconnected_streams_do_not_execute_partial_tools(self):
        fixtures=[('chat',[{'choices':[{'delta':{'tool_calls':[dict(chat_call(),index=0)]}}]}]),
                  ('messages',[{'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'a','name':'web_search','input':{}}}])]
        for protocol,events in fixtures:
            result,_,backend,_=self.run_loop(protocol,[Wire(events)],True)
            self.assertEqual(result['research']['failure']['kind'],'uncertain'); self.assertFalse(backend.searches)


if __name__=='__main__': unittest.main()

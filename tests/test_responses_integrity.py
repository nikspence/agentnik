"""Responses integrity and persisted partial-history regression checks (offline)."""
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentnik import core, hosted, research, responses_tools, storage
from agentnik.tools import Runtime
from test_routing import C, Wire, citation, function_call, message, response
from test_research import Backend, MESSAGES


class ResponsesIntegrity(unittest.TestCase):
    def managed(self, events):
        backend=Backend()
        with patch.object(core,'open_request',return_value=Wire(events)):
            result=research.run_managed(C,MESSAGES,'test-key',lambda _:None,threading.Event(),backend=backend)
        return result,backend

    def test_incomplete_or_conflicting_calls_never_execute(self):
        call=function_call()
        cases=[
            [{'type':'response.output_item.added','output_index':0,'item':call},
             {'type':'response.output_item.done','output_index':0,'item':call},
             {'type':'response.function_call_arguments.delta','output_index':0,'delta':'x'}],
            [{'type':'response.output_item.added','output_index':0,'item':call},
             {'type':'response.function_call_arguments.delta','output_index':0,'item_id':'different','delta':'x'}],
            [{'type':'response.output_item.added','output_index':0,'item':call},
             {'type':'response.completed','response':{'status':'completed'}}],
            [{'type':'response.output_item.added','output_index':0,'item':call},
             {'type':'response.completed','response':response([dict(call,call_id='different')])}],
            [{'type':'response.output_item.added','output_index':0,'item':call}]*2,
            [{'type':'response.completed','response':response([dict(call,status='in_progress')])}],
            [{'type':'response.output_item.added','output_index':0,'item':call}],
        ]
        for events in cases:
            with self.subTest(events=events):
                result,backend=self.managed(events)
                self.assertEqual(result['status'],'failed')
                self.assertFalse(backend.searches)
                self.assertFalse(result['research']['continuation_eligible'])

    def test_empty_final_output_clears_partial_call_and_text(self):
        events=[{'type':'response.output_item.added','output_index':0,'item':function_call()},
                {'type':'response.output_text.delta','output_index':1,'delta':'stale'},
                {'type':'response.completed','response':response([])}]
        result,backend=self.managed(events)
        self.assertEqual(result['status'],'failed'); self.assertIn('no final answer',result['error']); self.assertFalse(backend.searches)
        self.assertEqual(result['text'],''); self.assertEqual(result['research']['response_items'],[])

    def test_final_identity_preserves_opaque_reasoning(self):
        state={}; accumulator=responses_tools.Accumulator(Runtime(),state,lambda _:None)
        item={'type':'reasoning','id':'opaque','summary':[],'encrypted_content':'retain-verbatim'}
        accumulator.feed({'type':'response.output_item.added','output_index':0,'item':item})
        accumulator.feed({'type':'response.completed','response':response([item])})
        self.assertEqual(state['output'],[item])
        with self.assertRaisesRegex(ValueError,'after completion'):
            accumulator.feed({'type':'response.completed','response':response([item])})

    def test_final_function_item_id_may_change_only_for_same_complete_call(self):
        from agentnik.tools import ResearchError
        original=dict(function_call(),id='stream-id');final=dict(original,id='final-id')
        def finish(updated):
            state={};accumulator=responses_tools.Accumulator(Runtime(),state,lambda _:None)
            accumulator.feed({'type':'response.output_item.added','output_index':0,'item':original})
            accumulator.feed({'type':'response.output_item.done','output_index':0,'item':original})
            accumulator.feed({'type':'response.completed','response':response([updated])})
            return state
        self.assertEqual(finish(final)['output'],[final])
        formatted=dict(final,arguments=json.dumps(json.loads(original['arguments']),indent=2))
        self.assertEqual(finish(formatted)['output'],[formatted])
        for change in ({'call_id':'other'},{'name':'other'},{'arguments':'{"query":"other"}'},{'call_id':''}):
            with self.subTest(change=change),self.assertRaises(ResearchError):finish(dict(final,**change))

    def test_reformatted_argument_comparison_rejects_ambiguous_json(self):
        from agentnik.responses_tools import same_call_arguments
        self.assertTrue(same_call_arguments('{"b":2,"a":1}','{ "a": 1, "b": 2 }'))
        self.assertFalse(same_call_arguments('{"a":1,"a":2}','{"a":2}'))
        self.assertFalse(same_call_arguments('{"a":true}','{"a":1}'))

    def test_reordered_calls_are_correlated_and_changed_calls_are_rejected(self):
        first=dict(function_call(),id='first');second=dict(function_call('call-2'),id='second')
        def begin():
            state={};accumulator=responses_tools.Accumulator(Runtime(),state,lambda _:None)
            accumulator.feed({'type':'response.output_item.added','output_index':0,'item':first})
            accumulator.feed({'type':'response.output_item.added','output_index':1,'item':second})
            return state,accumulator
        state,accumulator=begin();final=[dict(second,id='changed'),first]
        accumulator.feed({'type':'response.completed','response':response(final)})
        self.assertEqual(state['output'],final)
        state,accumulator=begin()
        with self.assertRaises(responses_tools.ResponseIdentityError) as caught:
            accumulator.feed({'type':'response.completed','response':response([dict(second,id='changed',arguments='{"query":"changed"}'),first])})
        self.assertTrue(caught.exception.other_match);self.assertEqual(caught.exception.call_fields['arguments'],'different')
        empty=responses_tools.Accumulator(Runtime(),{},lambda _:None)
        empty.feed({'type':'response.output_item.added','output_index':0,'item':{'type':'function_call','id':'stream'}})
        with self.assertRaises(responses_tools.ResponseIdentityError) as caught:
            empty.feed({'type':'response.completed','response':response([dict(first,id='final')])})
        self.assertEqual(set(caught.exception.call_fields.values()),{'stream_missing'})

    def test_reordered_call_batch_executes_each_once(self):
        first=dict(function_call(),id='first');second=dict(function_call('call-2'),id='second');backend=Backend();bodies=[]
        replies=[Wire([{'type':'response.output_item.added','output_index':0,'item':first},
                       {'type':'response.output_item.added','output_index':1,'item':second},
                       {'type':'response.completed','response':response([dict(second,id='final-second'),dict(first,id='final-first')])}]),
                 Wire([{'type':'response.completed','response':response([message('Done')])}])]
        def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,MESSAGES,'test-key',lambda _:None,threading.Event(),backend=backend)
        self.assertEqual(result['status'],'ok');self.assertEqual(len(backend.searches),2)
        self.assertEqual([item['call_id'] for item in bodies[1]['input'] if item.get('type')=='function_call_output'],['call-2','call-1'])

    def test_reconciled_function_id_executes_once_and_continues(self):
        original=dict(function_call(),id='stream-id');final=dict(original,id='final-id');backend=Backend();bodies=[]
        replies=[Wire([{'type':'response.output_item.added','output_index':0,'item':original},
                       {'type':'response.output_item.done','output_index':0,'item':original},
                       {'type':'response.completed','response':response([final])}]),
                 Wire([{'type':'response.completed','response':response([message('Done')])}])]
        def send(connection,url,body,timeout):
            bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):
            result=research.run_managed(C,MESSAGES,'test-key',lambda _:None,threading.Event(),backend=backend)
        self.assertEqual(result['status'],'ok');self.assertEqual(len(backend.searches),1)
        outputs=[item for item in bodies[1]['input'] if item.get('type')=='function_call_output']
        self.assertEqual([item['call_id'] for item in outputs],[original['call_id']])

    def test_multiblock_citations_remain_local_to_their_text(self):
        # The invalid first span fits the combined answer but exceeds its own block.
        output=message('abc',[citation(1,6)])
        output['content'].append({'type':'output_text','text':'defghi','annotations':[citation(0,3)]})
        with patch.object(core,'open_request',return_value=Wire([{'type':'response.completed','response':response([output])}])):
            result=hosted.run_hosted(C,MESSAGES,'',lambda _:None,threading.Event())
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['text'],'abc\n\ndefghi')
        self.assertEqual(result['research']['unverified_annotations'],1)
        self.assertEqual([(a['start_index'],a['end_index']) for a in result['research']['annotations']],[(5,8)])

    def test_partial_audit_survives_storage_without_becoming_history(self):
        result,backend=self.managed([
            {'type':'response.output_item.added','output_index':0,'item':function_call()},
            {'type':'response.output_text.delta','output_index':1,'delta':'partial answer'}])
        self.assertFalse(backend.searches)
        self.assertTrue(result['research']['response_items'])
        with tempfile.TemporaryDirectory() as directory:
            store=storage.Store(directory)
            try:
                session=store.new_session('chat','Test',C)
                session['messages']=MESSAGES+[dict(role='assistant',**result)]
                store.save(session)
                saved=store.list_sessions()[0]
            finally: store.db.close()
        self.assertEqual(saved['messages'][-1]['text'],'partial answer')
        # The research state is authoritative even for older imports lacking outer status.
        saved['messages'][-1].pop('status')
        for protocol,url in [('responses',C['url']),('chat','https://gateway.example/v1'),
                             ('messages','https://gateway.example/v1'),('chat','http://localhost:11434/v1')]:
            body=core.chat_body(dict(C,protocol=protocol,url=url),saved['messages'])
            self.assertNotIn('partial answer',json.dumps(body))
            self.assertNotIn('call-1',json.dumps(body))


if __name__=='__main__': unittest.main()

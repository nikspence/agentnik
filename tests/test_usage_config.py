"""Offline usage snapshot and non-destructive configuration checks."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentnik import core, research, routing, storage
from agentnik.tools import Runtime
from test_routing import Wire
from test_research import Backend, MESSAGES


class UsageSnapshots(unittest.TestCase):
    def test_cache_and_reasoning_details_do_not_double_count(self):
        m=core.usage_metrics({'usage':{'input_tokens':100,'output_tokens':20,'input_tokens_details':{'cached_tokens':60},'output_tokens_details':{'reasoning_tokens':8}}})
        self.assertEqual(m,{'input_tokens':100,'output_tokens':20,'cached_input_tokens':60,'reasoning_output_tokens':8})
        m=core.usage_metrics({'usage':{'input_tokens':10,'cache_read_input_tokens':60,'cache_creation_input_tokens':30,'output_tokens':20}})
        self.assertEqual(m['input_tokens'],100); self.assertEqual(m['cached_input_tokens'],60)
        self.assertEqual(m['cache_creation_input_tokens'],30)

    def test_unknown_or_hostile_usage_is_not_retained(self):
        values={'input_tokens':True,'output_tokens':-1,'prompt_tokens':float('inf'),'completion_tokens':10**500,
                'api_key':'secret','input_tokens_details':{'cached_tokens':3,'private':'secret'}}
        self.assertEqual(core.usage_snapshot(values),{'input_tokens_details':{'cached_tokens':3}})
        self.assertEqual(core.usage_metrics({'usage':[]}),{})
        self.assertEqual(core.usage_metrics({}),{})

    def test_messages_cumulative_usage_is_one_request_snapshot(self):
        events=[{'type':'message_start','message':{'usage':{'input_tokens':10,'cache_read_input_tokens':60,'cache_creation_input_tokens':30}}},
                {'type':'content_block_start','index':0,'content_block':{'type':'text','text':'Done'}},
                {'type':'content_block_stop','index':0},
                {'type':'message_delta','delta':{'stop_reason':None},'usage':{'output_tokens':2}},
                {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':5}},
                {'type':'message_stop'}]
        c={'url':'https://gateway.example/v1','protocol':'messages','model':'mock'}
        with patch.object(core,'open_request',return_value=Wire(events)):
            result=research.run_managed(c,MESSAGES,'fixture',lambda _:None,threading.Event(),backend=Backend())
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['metrics']['input_tokens'],100)
        self.assertEqual(result['metrics']['output_tokens'],5)
        self.assertEqual(len(result['research']['provider_usage']),1)
        self.assertEqual(result['research']['provider_usage'][0]['input_tokens'],10)
        with patch.object(core,'open_request',return_value=Wire(events)):
            normal=core.run_request(c,'chat',core.chat_body(c,MESSAGES),lambda _:None,threading.Event())
        self.assertEqual(normal['metrics']['input_tokens'],100)
        self.assertEqual(normal['metrics']['output_tokens'],5)

    def test_multirequest_cache_counts_and_numeric_snapshots(self):
        from test_compat_tools import chat, chat_call
        c={'url':'https://gateway.example/v1','protocol':'chat','model':'mock','stream':False}
        first=chat(calls=[chat_call()],finish='tool_calls')
        second=chat('Answer [S1]')
        for value,cached in ((first,4),(second,6)):
            value['usage']['prompt_tokens_details']={'cached_tokens':cached}
            value['usage']['private_extension']='not retained'
        with patch.object(core,'open_request',side_effect=[Wire(first,False),Wire(second,False)]):
            result=research.run_managed(c,MESSAGES,'fixture',lambda _:None,threading.Event(),backend=Backend())
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['metrics']['input_tokens'],20)
        self.assertEqual(result['metrics']['cached_input_tokens'],10)
        self.assertEqual(len(result['research']['provider_usage']),2)
        self.assertNotIn('not retained',json.dumps(result['research']['provider_usage']))

    def test_aggregation_includes_failed_attempts_and_preserves_unknowns(self):
        values=[{'metrics':{'model_requests':1,'input_tokens':10,'cached_input_tokens':4,'reasoning_output_tokens':2,'usage_complete':False}},
                {'metrics':{'model_requests':1,'input_tokens':20,'output_tokens':5,'cached_input_tokens':6,'usage_complete':True,'last_input_tokens':20}}]
        m=routing.aggregate(values,Runtime())
        self.assertEqual(m['input_tokens'],30); self.assertEqual(m['cached_input_tokens'],10)
        self.assertEqual(m['reasoning_output_tokens'],2); self.assertFalse(m['usage_complete'])
        self.assertNotIn('cache_creation_input_tokens',m)


class ConfigurationRecovery(unittest.TestCase):
    def test_invalid_settings_preserve_original_and_do_not_create_database(self):
        cases=['{broken',json.dumps([]),json.dumps({'version':99}),json.dumps({'settings':[]}),
               json.dumps({'connections':{'x':{'url':'http://localhost','api_key':123}}}),
               json.dumps({'web_backends':[{'id':'x'},{'id':'x'}]}),
               json.dumps({'settings':{'font_size':'private-secret'}})]
        for content in cases:
            with self.subTest(content=content),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'connections.json';path.write_text(content,encoding='utf-8')
                with self.assertRaises(storage.ConfigurationError) as caught: storage.Store(directory)
                self.assertNotIn('private-secret',str(caught.exception))
                self.assertEqual(path.read_text(encoding='utf-8'),content)
                self.assertFalse((Path(directory)/'history.sqlite3').exists())
                # User repair allows the same data directory to reopen normally.
                path.write_text('{"connections":{},"settings":{}}',encoding='utf-8')
                store=storage.Store(directory);store.db.close()

    def test_legacy_config_keeps_credentials_unknown_fields_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'connections.json'
            config={'connections':{'example':{'url':'https://example.com/v1','credential_id':'existing-ref'}},'unknown_extension':{'retained':True}}
            path.write_text(json.dumps(config),encoding='utf-8')
            store=storage.Store(directory)
            try:
                self.assertEqual(store.config['connections'],config['connections'])
                self.assertEqual(store.config['settings'],{})
                store.flush();self.assertEqual(json.loads(path.read_text())['unknown_extension'],{'retained':True})
            finally: store.db.close()


if __name__=='__main__': unittest.main()

"""Offline checks for the opt-in compatibility CLI; no live requests."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import live_compat
from agentnik import core

ARGS=['--url','https://gateway.example/v1','--protocol','responses','--model','explicit-model','--route','managed','--backend','ollama']


class LiveCompatibilityCLI(unittest.TestCase):
    def test_default_plan_reads_no_keys_or_endpoints_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(Path,'read_text',side_effect=AssertionError('Must not read key files')),patch.object(core,'open_request') as request,contextlib.redirect_stdout(io.StringIO()) as out:
            target=Path(directory)/'report.json'
            self.assertEqual(live_compat.main(ARGS+['--key-file','missing','--output',str(target)]),0)
            plan=json.loads(out.getvalue());self.assertFalse(plan['execute'])
            self.assertFalse(plan['automatic_retries']);request.assert_not_called();self.assertFalse(target.exists())

    def test_invalid_hosted_target_and_existing_report_fail_before_request(self):
        with patch.object(core,'open_request') as request,contextlib.redirect_stderr(io.StringIO()),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):live_compat.main(['--url','https://gateway.example/v1','--protocol','responses','--model','explicit','--route','hosted','--execute'])
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'existing.json';path.write_text('original')
                with self.assertRaises(SystemExit):live_compat.main(ARGS+['--execute','--search-key-file','missing','--output',str(path)])
                self.assertEqual(path.read_text(),'original')
            request.assert_not_called()

    def test_managed_success_records_scope_without_transcripts_or_secrets(self):
        result={'status':'ok','text':'PRIVATE ANSWER [S1]','thinking':'PRIVATE REASONING','metrics':{'model_requests':3,'input_tokens':12,'unknown':'PRIVATE USAGE'},
                'research':{'tool_records':[{'name':'web_search','status':'completed'},{'name':'web_fetch','status':'completed'}],
                            'sources':[{'id':'S1','url':'https://example.com/','backend':'ollama-search'},{'id':'S2','url':'https://example.com/page','backend':'public-fetch'}]}}
        with tempfile.TemporaryDirectory() as directory:
            key=Path(directory)/'model.key';key.write_text('model-secret')
            search=Path(directory)/'search.key';search.write_text('search-secret');report=Path(directory)/'report.json'
            with patch.object(live_compat.research,'run_managed',return_value=result) as run,patch.object(live_compat,'revision',return_value={'commit':'mock','dirty':False}),contextlib.redirect_stdout(io.StringIO()) as out:
                code=live_compat.main(ARGS+['--execute','--key-file',str(key),'--search-key-file',str(search),'--output',str(report)])
            self.assertEqual(code,0);self.assertEqual(run.call_count,1)
            data=json.loads(report.read_text());self.assertEqual(data['outcome'],'passed')
            self.assertTrue(data['managed_search_succeeded']);self.assertTrue(data['public_fetch_succeeded']);self.assertTrue(data['continuation_completed'])
            for secret in ('model-secret','search-secret','PRIVATE ANSWER','PRIVATE REASONING','PRIVATE USAGE'):
                self.assertNotIn(secret,report.read_text()+out.getvalue())

    def test_upstream_failure_does_not_leak_raw_error_or_retry(self):
        with patch.object(live_compat.research,'run_managed',side_effect=core.EndpointError(401,'upstream-private-body')) as run,patch.object(live_compat,'revision',return_value={}),contextlib.redirect_stdout(io.StringIO()) as out,tempfile.TemporaryDirectory() as directory:
            key=Path(directory)/'search.key';key.write_text('search-secret')
            self.assertEqual(live_compat.main(ARGS+['--execute','--search-key-file',str(key)]),1)
            self.assertEqual(run.call_count,1);self.assertNotIn('upstream-private-body',out.getvalue())
            self.assertIn('401',out.getvalue())

    def test_chat_executes_one_bounded_protocol_request(self):
        from test_routing import Wire, response, message
        args=['--url','https://gateway.example/v1','--model','explicit','--protocol','responses','--route','chat','--execute']
        with patch.object(core,'open_request',return_value=Wire([{'type':'response.completed','response':response([message('Agentnik connected')])}])) as request,patch.object(live_compat,'revision',return_value={}),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(live_compat.main(args),0)
            request.assert_called_once();self.assertIn('"exact_chat_reply": true',out.getvalue())

    def test_cancellation_returns_sanitized_report_and_does_not_retry(self):
        def cancelled(*args,**kwargs):
            kwargs['runtime'].cancel.set();raise InterruptedError('private upstream detail')
        with tempfile.TemporaryDirectory() as directory,patch.object(live_compat.research,'run_managed',side_effect=cancelled) as run,patch.object(live_compat,'revision',return_value={}),contextlib.redirect_stdout(io.StringIO()) as out:
            key=Path(directory)/'search.key';key.write_text('search-secret')
            self.assertEqual(live_compat.main(ARGS+['--execute','--search-key-file',str(key)]),130)
            run.assert_called_once();self.assertNotIn('private upstream detail',out.getvalue())
            self.assertIn('"outcome": "cancelled"',out.getvalue())

    def test_model_answer_without_real_search_is_not_a_search_pass(self):
        result={'status':'ok','text':'Answer','metrics':{},'research':{}}
        summary=live_compat.summarize(result,{},'managed')
        self.assertEqual(summary['outcome'],'completed_without_required_activity')
        self.assertFalse(summary['managed_search_succeeded'])


if __name__=='__main__':unittest.main()

"""Snapshot contract for independent review, with no model requests."""
import hashlib
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agentnik.code_agent import ProjectFiles, REVIEW_RUBRICS
from agentnik.independent_review import prepare_snapshot, sources_unchanged, validate_result, build_review_request, preflight_review_batch, execute_review_batch, parse_structured_findings, RUBRIC_VERSION
from agentnik.project_tools import ProjectToolError
from agentnik import core
from agentnik.tools import Runtime, Limits, LimitError


class IndependentReviewSnapshots(unittest.TestCase):
    def test_batch_scheduler_runs_independent_passes_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('spec',encoding='utf-8');files=ProjectFiles(root);snapshot=prepare_snapshot(files,'spec.md','rubric ',[]);passes=[]
            for name in ('one','two'):
                connection={'url':'https://'+name+'.example.invalid/v1','protocol':'chat','model':name,'stream':False}
                proposal={'operation':'independent_review','role':'design','cwd':root,'path':'spec.md','model':name,'destination':core.endpoint(connection),'diff':snapshot['prompt'],'source_sha256':snapshot['source_sha256'],'evidence':snapshot['evidence'],'payload_sha256':snapshot['payload_sha256'],'payload_bytes':snapshot['payload_bytes']}
                passes.append({'approved':True,'connection':connection,'proposal':proposal,'snapshot':snapshot})
            barrier=threading.Barrier(2);calls=[];lock=threading.Lock()
            def send(connection,body,child):
                with lock:calls.append(connection['model'])
                barrier.wait(timeout=3)
                if connection['model']=='two':raise ValueError('do not expose secret')
                return 'Finding secret-token'
            result=execute_review_batch(files,passes,Runtime(),send,[threading.Event(),threading.Event()],model_timeout=5,secrets=['secret-token'])
            self.assertEqual(sorted(calls),['one','two']);self.assertEqual([r['status'] for r in result],['completed','failed'])
            self.assertEqual(result[0]['analysis'],'Finding [redacted]');self.assertNotIn('secret',str(result))

    def test_batch_completion_is_reported_before_slow_sibling_finishes(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('spec',encoding='utf-8');files=ProjectFiles(root);snapshot=prepare_snapshot(files,'spec.md','rubric ',[]);passes=[]
            for name in ('fast','slow'):
                connection={'url':'https://'+name+'.example.invalid/v1','protocol':'chat','model':name,'stream':False}
                proposal={'operation':'independent_review','role':'design','cwd':root,'path':'spec.md','model':name,'destination':core.endpoint(connection),'diff':snapshot['prompt'],'source_sha256':snapshot['source_sha256'],'evidence':snapshot['evidence'],'payload_sha256':snapshot['payload_sha256'],'payload_bytes':snapshot['payload_bytes']}
                passes.append({'approved':True,'connection':connection,'proposal':proposal,'snapshot':snapshot})
            started=threading.Barrier(2);release=threading.Event();done=threading.Event();updates=[];result=[]
            def send(connection,body,child):
                started.wait(timeout=3)
                if connection['model']=='slow':release.wait(3)
                return {'text':'finding','usage':{'input_tokens':10,'output_tokens':None}}
            def report(index,value):
                updates.append((index,copy.deepcopy(value)))
                if index==0:done.set()
            def run():result.extend(execute_review_batch(files,passes,Runtime(),send,[threading.Event(),threading.Event()],model_timeout=5,on_complete=report))
            thread=threading.Thread(target=run);thread.start()
            try:
                self.assertTrue(done.wait(2));self.assertTrue(thread.is_alive());self.assertEqual(updates[0][0],0);self.assertEqual(updates[0][1]['usage'],{'input_tokens':10,'output_tokens':None})
            finally:release.set();thread.join(5)
            self.assertFalse(thread.is_alive());self.assertEqual([item['status'] for item in result],['completed','completed'])

    def test_batch_scheduler_discards_changed_and_cancelled_results(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'spec.md');source.write_text('spec',encoding='utf-8');files=ProjectFiles(root);snapshot=prepare_snapshot(files,'spec.md','rubric ',[])
            connection={'url':'https://one.example.invalid/v1','protocol':'chat','model':'one','stream':False}
            proposal={'operation':'independent_review','role':'design','cwd':root,'path':'spec.md','model':'one','destination':core.endpoint(connection),'diff':snapshot['prompt'],'source_sha256':snapshot['source_sha256'],'evidence':snapshot['evidence'],'payload_sha256':snapshot['payload_sha256'],'payload_bytes':snapshot['payload_bytes']}
            item={'approved':True,'connection':connection,'proposal':proposal,'snapshot':snapshot}
            def change(connection,body,child):source.write_text('changed',encoding='utf-8');return 'stale finding'
            result=execute_review_batch(files,[item],Runtime(),change,[threading.Event()],model_timeout=5)
            self.assertEqual(result,[{'status':'stale'}])
            source.write_text('spec',encoding='utf-8');cancel=threading.Event();calls=[]
            def cancelled(connection,body,child):calls.append(1);cancel.set();return 'late finding'
            result=execute_review_batch(files,[item,item],Runtime(),cancelled,[cancel,threading.Event()],model_timeout=5)
            self.assertEqual([r['status'] for r in result],['cancelled','skipped']);self.assertEqual(len(calls),1);self.assertNotIn('late finding',str(result))

    def test_batch_preflight_requires_each_approval_and_reserves_before_start(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root,'spec.md');path.write_text('specification',encoding='utf-8');files=ProjectFiles(root)
            snapshot=prepare_snapshot(files,'spec.md','rubric ',[])
            connection={'url':'https://example.invalid/v1','protocol':'chat','model':'reviewer','api_key':'secret','stream':False}
            proposal={'operation':'independent_review','role':'design','cwd':root,'path':'spec.md','model':'reviewer','destination':core.endpoint(connection),'diff':snapshot['prompt'],'source_sha256':snapshot['source_sha256'],'evidence':snapshot['evidence'],'payload_sha256':snapshot['payload_sha256'],'payload_bytes':snapshot['payload_bytes']}
            item={'approved':True,'connection':connection,'proposal':proposal,'snapshot':snapshot}
            runtime=Runtime(limits=Limits(requests=3,context_bytes=2048))
            prepared=preflight_review_batch(files,[item,copy.deepcopy(item)],runtime)
            self.assertEqual((runtime.requests,runtime.context_bytes),(2,2*snapshot['payload_bytes']))
            self.assertEqual(len(prepared),2);self.assertNotIn('secret',json.dumps(prepared))
            for changed in (dict(item,approved=False),dict(item,proposal=dict(proposal,model='other')),dict(item,snapshot=dict(snapshot,sources=[]))):
                current=Runtime(limits=Limits(requests=3,context_bytes=2048))
                with self.assertRaises(ValueError):preflight_review_batch(files,[item,changed],current)
                self.assertEqual((current.requests,current.context_bytes),(0,0))
            current=Runtime(limits=Limits(requests=1,context_bytes=2048))
            with self.assertRaises(LimitError):preflight_review_batch(files,[item,item],current)
            self.assertEqual((current.requests,current.context_bytes),(0,0))
            path.write_text('changed',encoding='utf-8');current=Runtime()
            with self.assertRaises(ValueError):preflight_review_batch(files,[item],current)
            self.assertEqual((current.requests,current.context_bytes),(0,0))

    def test_structured_findings_are_bounded_all_or_nothing(self):
        finding={'severity':'medium','title':'Missing criterion','rationale':'No success threshold.','location':'spec.md:12','assumptions':'Threshold is needed.','verification':'Ask the owner.'}
        payload={'version':1,'findings':[finding,finding]}
        result=parse_structured_findings(json.dumps(payload))
        self.assertEqual(result['status'],'valid');self.assertEqual([item['id'] for item in result['findings']],['finding-1','finding-2'])
        self.assertEqual(parse_structured_findings('{"version":1,"findings":[]}')['status'],'valid')
        cases=['not json','{"version":1,"version":1,"findings":[]}',json.dumps({'version':2,'findings':[]}),json.dumps({'version':True,'findings':[]}),json.dumps({'version':1,'findings':[finding,dict(finding,severity='critical')]}),json.dumps({'version':1,'findings':[finding]*11}),json.dumps({'version':1,'findings':[dict(finding,title='x'*161)]}),json.dumps({'version':1,'findings':[dict(finding,extra='x')]})]
        for text in cases:
            with self.subTest(text=text[:50]):self.assertEqual(parse_structured_findings(text),{'status':'invalid','findings':[]})
        self.assertEqual(parse_structured_findings('x'*16001),{'status':'too_large','findings':[]})
        self.assertEqual(parse_structured_findings(json.dumps(payload),truncated=True),{'status':'truncated','findings':[]})
        with self.assertRaises(ValueError):parse_structured_findings('{}',truncated=1)

    def test_approved_request_is_fresh_and_bound_to_payload_and_destination(self):
        prompt='Fixed rubric and reviewed document';payload_hash=hashlib.sha256(prompt.encode()).hexdigest()
        for protocol,url in [('chat','https://example.invalid/v1'),('responses','https://example.invalid/v1'),('messages','https://example.invalid/v1'),('chat','http://localhost:11434')]:
            with self.subTest(protocol=protocol,url=url):
                connection={'url':url,'protocol':protocol,'model':'reviewer','stream':False}
                proposal={'operation':'independent_review','diff':prompt,'payload_sha256':payload_hash,'payload_bytes':len(prompt.encode()),'model':'reviewer','destination':core.endpoint(connection)}
                body=build_review_request(connection,proposal)
                messages=body['input' if protocol=='responses' else 'messages']
                self.assertEqual(len(messages),1);self.assertEqual(messages[0]['role'],'user');self.assertEqual(messages[0]['content'],prompt)
                self.assertNotIn('tools',body)
                if protocol=='responses':self.assertIs(body['store'],False)
                for field,value in [('diff','changed'),('payload_sha256','0'*64),('payload_bytes',1),('destination','https://other.invalid'),('model','other')]:
                    changed=dict(proposal,**{field:value})
                    with self.assertRaises(ValueError):build_review_request(connection,changed)
                with self.assertRaises(ValueError):build_review_request(dict(connection,model='other'),proposal)

    def test_version_one_rubrics_keep_exact_instruction_text(self):
        expected={'comprehension':'e649e48be400fb096d9c34bb6b69cb120cbdd2229c423761cd1f73cb208acb3f','requirements':'724d70b25b6ce2f2ece2a40211f1589b4fb509c236d750b0186483c65fab16a8','design':'baf8665a82ad8898adafcf175344908424173ce169d792c2389826a07ec02402','readiness':'5a2f6e74072d11c300a50a81fb46c805282c834a41822d83756e5a4ed8cc3efc'}
        self.assertEqual(RUBRIC_VERSION,1)
        self.assertEqual({name:hashlib.sha256(text.encode('utf-8')).hexdigest() for name,text in REVIEW_RUBRICS.items()},expected)

    def test_result_contract_rejects_invalid_or_future_values(self):
        result={'version':1,'rubric_version':1,'status':'completed','role':'design','path':'spec.md','source_sha256':'a'*64,'evidence':[], 'model':'model','usage':{'input_tokens':None,'output_tokens':4},'elapsed_seconds':1.2,'analysis':'Untrusted finding','truncated':False,'notice':'Untrusted','payload_sha256':'b'*64}
        validated=validate_result(result);self.assertEqual(validated,result);self.assertIsNot(validated['usage'],result['usage'])
        for field,invalid in [('version',2),('rubric_version',True),('status','running'),('role',[]),('source_sha256','bad'),('analysis','x'*8001),('truncated',1),('usage',{'input_tokens':float('nan'),'output_tokens':0}),('elapsed_seconds',float('inf'))]:
            with self.subTest(field=field):
                changed=copy.deepcopy(result);changed[field]=invalid
                with self.assertRaises(ValueError):validate_result(changed)
        failed={k:v for k,v in result.items() if k not in ('analysis','truncated','notice','payload_sha256')};failed.update(status='cancelled',error='Cancelled')
        self.assertEqual(validate_result(failed)['status'],'cancelled')

    def test_payload_hash_redaction_and_changed_sources(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);(folder/'spec.md').write_text('target secret-token',encoding='utf-8');source=folder/'source.py';source.write_text('evidence secret-token',encoding='utf-8')
            files=ProjectFiles(root);charges=[]
            snapshot=prepare_snapshot(files,'spec.md','Fixed rubric\n',['secret-token'],json.dumps(['source.py']),lambda:charges.append(1))
            self.assertEqual(charges,[1]);self.assertNotIn('secret-token',snapshot['prompt'])
            self.assertEqual(snapshot['source_sha256'],hashlib.sha256(b'target secret-token').hexdigest())
            self.assertEqual(snapshot['payload_sha256'],hashlib.sha256(snapshot['prompt'].encode()).hexdigest())
            self.assertEqual(snapshot['payload_bytes'],len(snapshot['prompt'].encode()))
            self.assertNotEqual(snapshot['evidence'][0]['sha256'],snapshot['evidence'][0]['payload_sha256'])
            self.assertTrue(sources_unchanged(files,snapshot['sources']))
            source.write_text('changed',encoding='utf-8');self.assertFalse(sources_unchanged(files,snapshot['sources']))
            source.unlink();self.assertFalse(sources_unchanged(files,snapshot['sources']))

    def test_invalid_or_duplicate_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'spec.md').write_text('target',encoding='utf-8');files=ProjectFiles(root)
            for paths in ('[]','["spec.md"]','["../outside"]','["missing"]','["a","b","c","d"]','bad'):
                with self.subTest(paths=paths),self.assertRaises(ProjectToolError):
                    prepare_snapshot(files,'spec.md','rubric',[],paths)

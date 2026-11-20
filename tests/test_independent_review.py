"""Snapshot contract for independent review, with no model requests."""
import hashlib
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agentnik.code_agent import ProjectFiles
from agentnik.independent_review import validate_review_history, parse_structured_findings
from agentnik.project_tools import ProjectToolError
from agentnik import core
from agentnik.tools import Runtime, Limits, LimitError


class IndependentReviewSnapshots(unittest.TestCase):
    def test_saved_endpoint_identity_rejects_unsafe_records(self):
        from agentnik.independent_review import validate_review_endpoint_identity
        self.assertEqual(validate_review_endpoint_identity({'protocol':'responses','origin':'https://example.invalid:8443'}),{'protocol':'responses','origin':'https://example.invalid:8443'})
        for origin in ('https://user:password@example.invalid','https://example.invalid/private-key','https://example.invalid?key=secret','https://example.invalid:99999','javascript://example.invalid'):
            with self.subTest(origin=origin),self.assertRaises(ValueError):validate_review_endpoint_identity({'protocol':'chat','origin':origin})

    def test_drift_review_records_are_valid_saved_history(self):
        review={'id':'a'*32+'-1','role':'drift','model':'light','path':'spec.md','source_sha256':'b'*64,'payload_sha256':'c'*64,'evidence':[{'path':'code.py','sha256':'d'*64,'payload_sha256':'e'*64}],'pass_status':'completed','structured':{'status':'valid','findings':[]},'dispositions':{}}
        history=[{'version':1,'id':'f'*32,'track_id':None,'reviews':[review]}]
        self.assertEqual(validate_review_history(history),history)
        review['rubric_version']=1;self.assertEqual(validate_review_history(history),history)
        review['endpoint']={'protocol':'chat','origin':'https://example.invalid'};self.assertEqual(validate_review_history(history),history)
        review['target_payload_sha256']='e'*64;self.assertEqual(validate_review_history(history),history)
        review['batch_approved_at']='2026-11-13T19:20:21Z';self.assertEqual(validate_review_history(history),history)
        for invalid in (None,123,'2026-02-30T12:00:00Z','2026-11-13T19:20:21+00:00','2026-11-13'):
            review['batch_approved_at']=invalid
            with self.subTest(approved_at=invalid),self.assertRaises(ValueError):validate_review_history(history)
        review['batch_approved_at']='2026-11-13T19:20:21Z'
        review['target_payload_sha256']='bad'
        with self.assertRaises(ValueError):validate_review_history(history)
        review['target_payload_sha256']='e'*64
        for invalid in (True,0,2,'1'):
            review['rubric_version']=invalid
            with self.subTest(rubric_version=invalid),self.assertRaises(ValueError):validate_review_history(history)
        review['rubric_version']=1
        review['role']='repository_fit';self.assertEqual(validate_review_history(history),history)
        review['measurements']={'input_tokens':10,'output_tokens':None,'elapsed_seconds':1.5}
        self.assertEqual(validate_review_history(history),history)
        for bad in (True,-1,float('nan'),float('inf'),'10'):
            review['measurements']['input_tokens']=bad
            with self.subTest(value=bad),self.assertRaises(ValueError):validate_review_history(history)
        review['measurements']['input_tokens']=10;review['pass_status']='interrupted';review['structured']={'status':'not_available','findings':[]}
        with self.assertRaises(ValueError):validate_review_history(history)
        del review['measurements'];review['pass_status']='failed';review['reason']='Reviewer request failed.'
        self.assertEqual(validate_review_history(history),history)
        for bad in ('',None,'x'*501):
            review['reason']=bad
            with self.subTest(reason=bad),self.assertRaises(ValueError):validate_review_history(history)
        review['reason']='Unexpected';review['pass_status']='completed';review['structured']={'status':'valid','findings':[]}
        with self.assertRaises(ValueError):validate_review_history(history)




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

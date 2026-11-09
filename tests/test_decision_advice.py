"""Offline validation of untrusted System One advisory responses."""
import io
import json
import threading
import unittest
from unittest.mock import patch
from agentnik import core
from agentnik.decision_advice import parse_advice,request


class AdviceValidation(unittest.TestCase):
    def test_request_sends_only_authorized_scope_with_bearer_endpoint(self):
        proposal={'command':'echo hello','cwd':'/project','shell':'/bin/sh','environment_keys':['PATH'],'environment_hash':'private-hash','other':'not sent'}
        connection={'url':'https://example.com/v1','protocol':'messages','model':'decision-model','api_key':'private-key'};calls=[]
        def open_request(c,url,body,timeout):
            calls.append((c,url,body,timeout));return io.BytesIO(json.dumps({'answers':{'risk':{'choice':'warning','confidence':.7}}}).encode())
        with patch.object(core,'open_request',side_effect=open_request):raw=request(connection,proposal,threading.Event())
        c,url,body,timeout=calls[0]
        self.assertEqual(url,'https://example.com/v1/systemone');self.assertEqual(c['protocol'],'chat');self.assertEqual(c['api_key'],'private-key')
        self.assertEqual(body['state'],{'command':'echo hello','cwd':'/project','shell':'/bin/sh','environment_keys':['PATH']})
        self.assertNotIn('private-key',json.dumps(body));self.assertNotIn('private-hash',json.dumps(body));self.assertNotIn('not sent',json.dumps(body))
        self.assertLessEqual(timeout,15);self.assertEqual(parse_advice(raw)['category'],'warning')

    def test_known_categories_and_optional_confidence(self):
        for category in ('safe','warning','risky','privacy','danger'):
            self.assertEqual(parse_advice({'answers':{'risk':{'choice':category,'confidence':.75}}}),{'category':category,'confidence':.75})
        self.assertEqual(parse_advice({'answers':{'risk':{'choice':'warning'}}}),{'category':'warning','confidence':None})

    def test_cancelled_check_never_starts_request(self):
        cancel=threading.Event();cancel.set()
        with patch.object(core,'open_request') as endpoint:
            with self.assertRaises(InterruptedError):request({'url':'https://example.com','model':'safety'}, {'command':'echo x','cwd':'/project','shell':'/bin/sh','environment_keys':[]},cancel)
            endpoint.assert_not_called()

    def test_untrusted_or_incomplete_answers_are_unknown(self):
        for value in (None,{}, {'answers':[]}, {'answers':{'risk':{'choice':'safe','confidence':True}}},
                      {'answers':{'risk':{'choice':'safe','confidence':float('nan')}}},
                      {'answers':{'risk':{'choice':'safe','confidence':1.1}}},
                      {'answers':{'risk':{'choice':['safe']}}}):
            self.assertEqual(parse_advice(value),{'category':'unknown','confidence':None})


if __name__=='__main__':unittest.main()

"""Offline Codex protocol fixtures. No Codex process or model is started."""
import json
import tempfile
import unittest
from pathlib import Path
from agentnik.codex_protocol import AppServerProtocol,ProtocolError


class AppServerContracts(unittest.TestCase):
    def adapter(self,path):
        sent=[];events=[];adapter=AppServerProtocol(sent.append,events.append);adapter.initialize()
        adapter.receive(json.dumps({'id':1,'result':{}}));adapter.activate('thread','turn',path)
        return adapter,sent,events

    def proposal(self,adapter,path,**extra):
        adapter.receive(json.dumps({'method':'item/started','params':{'threadId':'thread','turnId':'turn','item':{'id':'item','type':'commandExecution','command':'git status --short','cwd':str(path)}}}))
        params=dict(threadId='thread',turnId='turn',itemId='item',command='git status --short',cwd=str(path),**extra)
        adapter.receive(json.dumps({'id':90,'method':'item/commandExecution/requestApproval','params':params}))

    def test_handshake_and_exact_one_shot_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter,sent,events=self.adapter(directory);self.proposal(adapter,directory)
            fingerprint=events[-1]['fingerprint'];self.assertFalse(adapter.decide(90,'changed',True))
            self.assertTrue(adapter.decide(90,fingerprint,True));self.assertEqual(sent[-1],{'id':90,'result':{'decision':'accept'}})
            self.assertFalse(adapter.decide(90,fingerprint,True))
            self.assertEqual(sent[1]['method'],'initialized')

    def test_permissions_and_network_prompts_never_become_command_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            for extra in ({'networkApprovalContext':{'host':'example.com'}},{'additionalPermissions':{'fileSystem':{}}}):
                adapter,sent,events=self.adapter(directory);self.proposal(adapter,directory,**extra)
                self.assertEqual(sent[-1]['result']['decision'],'decline');self.assertFalse(adapter.pending)

    def test_unknown_request_and_stale_turn_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter,sent,events=self.adapter(directory);self.proposal(adapter,directory)
            fingerprint=events[-1]['fingerprint']
            adapter.receive(json.dumps({'method':'turn/completed','params':{'threadId':'thread','turnId':'turn'}}))
            self.assertFalse(adapter.decide(90,fingerprint,True))
            adapter.receive(json.dumps({'id':91,'method':'unknown/permissions','params':{}}))
            self.assertIn('error',sent[-1])
            adapter.close();self.assertFalse(adapter.decide(90,fingerprint,True))

    def test_malformed_duplicate_and_oversized_wire_data_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter,_,_=self.adapter(directory)
            for line in ('{bad','{"id":1,"id":2}', '[]'):
                with self.assertRaises(ProtocolError):adapter.receive(line)
            with self.assertRaises(ProtocolError):adapter.receive(' '*32001)
            self.assertTrue(adapter.closed)

    def test_wrong_directory_and_conflicting_command_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            other=Path(directory)/'other';other.mkdir()
            adapter,sent,_=self.adapter(directory);self.proposal(adapter,other)
            self.assertEqual(sent[-1]['result']['decision'],'decline')
            adapter,_,_=self.adapter(directory)
            with self.assertRaises(ProtocolError):adapter.activate('thread','turn',str(Path(directory)/'missing'))


if __name__=='__main__':unittest.main()

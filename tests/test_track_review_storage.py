"""Offline read-only project-local legacy review history."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agentnik.code_agent import ProjectFiles
from agentnik.track_execution import prepare_track
from agentnik.track_review_storage import read_sidecar,validate_sidecar,sidecar_path
from agentnik.independent_review import track_review_summary
from agentnik.code_agent import CodingRun
from agentnik import core
from unittest.mock import patch
from test_compat_tools import chat
from test_routing import Wire

FIXTURE=Path(__file__).parent/'fixtures'/'tracks'


class TrackReviewStorage(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'project';shutil.copytree(FIXTURE,self.root);self.files=ProjectFiles(self.root)
        self.track=prepare_track(self.files,'sample_feature');self.path=sidecar_path('sample_feature')
        self.snapshot={'version':1,'id':'a'*32,'track_id':None,'reviews':[{'id':'b'*32+'-1','role':'design','model':'light','path':'spec.md','source_sha256':'c'*64,'payload_sha256':'d'*64,'evidence':[],'track_context':{'id':'sample_feature','digest':self.track['digest']},'pass_status':'completed','structured':{'status':'valid','findings':[]},'dispositions':{}}]}

    def write_fixture(self, snapshots):
        content={'version':1,'track_id':'sample_feature','snapshots':snapshots}
        (self.root/self.path).write_text(json.dumps(content),encoding='utf-8')

    def test_existing_history_is_read_without_rewriting(self):
        self.assertEqual(read_sidecar(self.files,'sample_feature')['snapshots'],[])
        self.assertFalse((self.root/self.path).exists())
        self.snapshot['reviews'][0]['rubric_version']=1
        self.snapshot['reviews'][0]['batch_approved_at']='2026-11-13T19:20:21Z'
        self.snapshot['reviews'][0]['endpoint']={'protocol':'chat','origin':'https://example.invalid'}
        self.write_fixture([self.snapshot]);before=(self.root/self.path).read_bytes()
        self.assertEqual(read_sidecar(self.files,'sample_feature')['snapshots'],[self.snapshot])
        self.assertEqual((self.root/self.path).read_bytes(),before)

    def test_invalid_history_is_rejected_without_rewriting(self):
        for value in ({'version':2,'track_id':'sample_feature','snapshots':[]},{'version':1,'track_id':'other','snapshots':[]}):
            with self.assertRaises(ValueError):validate_sidecar(value,'sample_feature')
        self.write_fixture([self.snapshot]);path=self.root/self.path;path.write_text('{broken',encoding='utf-8')
        with self.assertRaises(ValueError):read_sidecar(self.files,'sample_feature')
        self.assertEqual(path.read_text(encoding='utf-8'),'{broken')

    def test_project_history_remains_separate_from_coding_requests(self):
        self.write_fixture([self.snapshot])
        summary=track_review_summary(self.files,self.track,[])
        self.assertEqual(len(summary['snapshots']),1);self.assertEqual(summary['snapshots'][0]['origin'],'project');self.assertEqual(summary['snapshots'][0]['snapshot_id'],self.snapshot['id'])
        duplicate=track_review_summary(self.files,self.track,[self.snapshot]);self.assertEqual([item['origin'] for item in duplicate['snapshots']],['session','project'])
        bodies=[];events=[]
        def send_ok(connection,url,body,timeout):bodies.append(body);return Wire(chat('Done'),False)
        with patch.object(core,'open_request',side_effect=send_ok):CodingRun({'url':'https://example.invalid/v1','protocol':'chat','model':'heavy','stream':False},self.root,'Work',selected_track=self.track).run(events.append)
        self.assertEqual(events[-1]['status'],'completed');self.assertNotIn(self.snapshot['id'],json.dumps(bodies))
        run=CodingRun({'url':'https://example.invalid/v1','protocol':'chat','model':'heavy','stream':False},self.root,'Work',selected_track=self.track)
        path=self.root/self.path;path.write_text('{"version":2}',encoding='utf-8');events=[]
        with patch.object(core,'open_request',side_effect=send_ok) as send:run.run(events.append)
        send.assert_called_once();self.assertEqual(events[-1]['status'],'completed');self.assertEqual(path.read_text(encoding='utf-8'),'{"version":2}')

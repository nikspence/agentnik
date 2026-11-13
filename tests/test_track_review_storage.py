"""Offline project-local review sidecar contract and approved writes."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agentnik.code_agent import ProjectFiles
from agentnik.track_execution import prepare_track
from agentnik.track_review_storage import read_sidecar,prepare_append,prepare_remove,apply_append,validate_sidecar,sidecar_path
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

    def test_approval_and_append_preserve_existing_history(self):
        self.assertEqual(read_sidecar(self.files,'sample_feature')['snapshots'],[])
        prepared=prepare_append(self.files,'sample_feature',self.snapshot);self.assertFalse((self.root/self.path).exists());self.assertIn('reviews.json',prepared['proposal']['diff'])
        self.assertEqual(apply_append(self.files,prepared,lambda proposal:False)['status'],'rejected');self.assertFalse((self.root/self.path).exists())
        self.assertEqual(apply_append(self.files,prepared,lambda proposal:True)['status'],'completed')
        second=copy.deepcopy(self.snapshot);second['id']='e'*32
        result=apply_append(self.files,prepare_append(self.files,'sample_feature',second),lambda proposal:True)
        self.assertEqual(result['status'],'completed');self.assertEqual([item['id'] for item in read_sidecar(self.files,'sample_feature')['snapshots']],[self.snapshot['id'],second['id']])
        with self.assertRaises(ValueError):prepare_append(self.files,'sample_feature',second)

    def test_conflicts_and_credential_or_foreign_track_rejected(self):
        prepared=prepare_append(self.files,'sample_feature',self.snapshot)
        def modify_track(proposal):
            (self.root/'agentnik-plans/tracks/sample_feature/plan.md').write_text('changed',encoding='utf-8');return True
        with self.assertRaises(ValueError):apply_append(self.files,prepared,modify_track)
        self.assertFalse((self.root/self.path).exists())
        with self.assertRaises(ValueError):prepare_append(self.files,'sample_feature',self.snapshot,secrets=['light'])
        foreign=copy.deepcopy(self.snapshot);foreign['reviews'][0]['track_context']['id']='other'
        with self.assertRaises(ValueError):prepare_append(self.files,'sample_feature',foreign)
        for value in ({'version':2,'track_id':'sample_feature','snapshots':[]},{'version':1,'track_id':'other','snapshots':[]}):
            with self.assertRaises(ValueError):validate_sidecar(value,'sample_feature')

    def test_sidecar_change_during_approval_stops_write(self):
        apply_append(self.files,prepare_append(self.files,'sample_feature',self.snapshot),lambda proposal:True)
        second=copy.deepcopy(self.snapshot);second['id']='e'*32;prepared=prepare_append(self.files,'sample_feature',second)
        external=self.root/self.path
        def change(proposal):external.write_text('external data',encoding='utf-8');return True
        with self.assertRaises(ValueError):apply_append(self.files,prepared,change)
        self.assertEqual(external.read_text(encoding='utf-8'),'external data')

    def test_removing_one_snapshot_requires_approval_and_detects_conflicts(self):
        apply_append(self.files,prepare_append(self.files,'sample_feature',self.snapshot),lambda proposal:True)
        second=copy.deepcopy(self.snapshot);second['id']='e'*32;apply_append(self.files,prepare_append(self.files,'sample_feature',second),lambda proposal:True)
        prepared=prepare_remove(self.files,'sample_feature',self.snapshot['id'])
        self.assertIn('-      "id": "'+self.snapshot['id'],prepared['proposal']['diff'])
        self.assertEqual(apply_append(self.files,prepared,lambda proposal:False)['status'],'rejected');self.assertEqual(len(read_sidecar(self.files,'sample_feature')['snapshots']),2)
        self.assertEqual(apply_append(self.files,prepared,lambda proposal:True)['status'],'completed')
        self.assertEqual([item['id'] for item in read_sidecar(self.files,'sample_feature')['snapshots']],[second['id']])
        with self.assertRaises(ValueError):prepare_remove(self.files,'sample_feature',self.snapshot['id'])
        prepared=prepare_remove(self.files,'sample_feature',second['id']);external=self.root/self.path
        def change(proposal):external.write_text('external',encoding='utf-8');return True
        with self.assertRaises(ValueError):apply_append(self.files,prepared,change)
        self.assertEqual(external.read_text(encoding='utf-8'),'external')

    def test_project_history_in_preview_and_pre_request_guard(self):
        apply_append(self.files,prepare_append(self.files,'sample_feature',self.snapshot),lambda proposal:True)
        summary=track_review_summary(self.files,self.track,[])
        self.assertEqual(len(summary['snapshots']),1);self.assertEqual(summary['snapshots'][0]['origin'],'project');self.assertEqual(summary['snapshots'][0]['snapshot_id'],self.snapshot['id'])
        duplicate=track_review_summary(self.files,self.track,[self.snapshot]);self.assertEqual([item['origin'] for item in duplicate['snapshots']],['session','project'])
        bodies=[];events=[]
        def send_ok(connection,url,body,timeout):bodies.append(body);return Wire(chat('Done'),False)
        with patch.object(core,'open_request',side_effect=send_ok):CodingRun({'url':'https://example.invalid/v1','protocol':'chat','model':'heavy','stream':False},self.root,'Work',selected_track=self.track,review_guard={'history':[],'summary':summary}).run(events.append)
        self.assertEqual(events[-1]['status'],'completed');self.assertNotIn(self.snapshot['id'],json.dumps(bodies))
        run=CodingRun({'url':'https://example.invalid/v1','protocol':'chat','model':'heavy','stream':False},self.root,'Work',selected_track=self.track,review_guard={'history':[],'summary':summary})
        path=self.root/self.path;path.write_text('{"version":2}',encoding='utf-8');events=[]
        with patch.object(core,'open_request') as send:run.run(events.append)
        send.assert_not_called();self.assertEqual(events[-1]['status'],'failed');self.assertEqual(path.read_text(encoding='utf-8'),'{"version":2}')

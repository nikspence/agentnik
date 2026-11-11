"""Directory moves and unrestricted single-file deletion."""
import json
import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from agentnik import core
from agentnik.code_agent import CodingRun,DirectoryMoveError,ProjectFiles
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire


class DirectoryAndDeletion(unittest.TestCase):
    def test_delete_large_binary_without_prior_content_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'asset.bin';target.write_bytes(b'\x00\xffPRIVATE-CONTENT'*200_000)
            events=[];bodies=[];count=0
            def send(connection,url,body,timeout):
                nonlocal count
                bodies.append(json.loads(json.dumps(body)));count+=1
                if count==1:return Wire(chat(calls=[call('delete_file',{'path':'asset.bin'})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),folder,'Delete asset').run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertFalse(target.exists())
            self.assertNotIn('PRIVATE-CONTENT',json.dumps(events)+json.dumps(bodies))
            self.assertFalse(any(e['kind']=='operation_proposal' for e in events))

    def test_delete_conflict_and_cancel_preserve_source(self):
        for scenario in ('change','cancel'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as folder:
                target=Path(folder)/'file.bin';target.write_bytes(b'\x00before');events=[]
                run=CodingRun(dict(C,stream=False),folder,'Delete file')
                replies=[Wire(chat(calls=[call('delete_file',{'path':'file.bin'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                def emit(event):
                    events.append(event)
                    if event.get('text','').startswith('Applying project delete_file:'):
                        if scenario=='cancel':run.stop()
                        else:target.write_bytes(b'changed content')
                with patch.object(core,'open_request',side_effect=replies):run.run(emit)
                self.assertEqual(target.read_bytes(),b'changed content' if scenario=='change' else b'\x00before')

    def test_directory_rename_and_move_preserve_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src/sub').mkdir(parents=True);(root/'dst').mkdir();(root/'src/sub/file.bin').write_bytes(b'\x00\xff')
            files=ProjectFiles(root)
            proposal=files.directory_move_proposal('src','renamed');files.apply_directory_move(proposal)
            self.assertFalse((root/'src').exists());self.assertEqual((root/'renamed/sub/file.bin').read_bytes(),b'\x00\xff')
            proposal=files.directory_move_proposal('renamed','dst/final');files.apply_directory_move(proposal)
            self.assertEqual((root/'dst/final/sub/file.bin').read_bytes(),b'\x00\xff')

    def test_directory_move_rejects_collisions_changes_and_protected_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src/sub').mkdir(parents=True);(root/'dst').mkdir();(root/'src/sub/file').write_text('before')
            files=ProjectFiles(root)
            for source,destination in (('.','dst/new'),('src','dst'),('src','src/sub/new'),('src','../outside'),('src','missing/new')):
                with self.subTest(source=source,destination=destination),self.assertRaises(ValueError):files.directory_move_proposal(source,destination)
            proposal=files.directory_move_proposal('src','dst/new');(root/'src/sub/file').write_text('changed content')
            with self.assertRaises(ValueError):files.apply_directory_move(proposal)
            self.assertTrue((root/'src/sub/file').exists());self.assertFalse((root/'dst/new').exists())
            (root/'src/.env').write_text('secret')
            with self.assertRaises(ValueError):files.directory_move_proposal('src','dst/new')
            (root/'src/.env').unlink();os.link(root/'src/sub/file',root/'src/sub/hardlink')
            with self.assertRaises(ValueError):files.directory_move_proposal('src','dst/new')

    def test_directory_scan_limit_fails_without_moving(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src').mkdir();(root/'src/a').write_text('a');(root/'src/b').write_text('b')
            with patch('agentnik.code_agent.MAX_DIRECTORY_ENTRIES',1),self.assertRaises(ValueError):ProjectFiles(root).directory_move_proposal('src','new')
            self.assertTrue((root/'src/a').exists());self.assertFalse((root/'new').exists())

    def test_directory_with_symlink_is_not_moved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src').mkdir();(root/'real').write_text('data')
            try:os.symlink(root/'real',root/'src/link')
            except OSError:self.skipTest('Creating symbolic links is unavailable')
            with self.assertRaises(ValueError):ProjectFiles(root).directory_move_proposal('src','new')
            self.assertTrue((root/'real').exists());self.assertFalse((root/'new').exists())

    def test_atomic_destination_collision_does_not_replace_directory(self):
        from agentnik.directory_ops import rename_directory_no_replace
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src').mkdir();(root/'src/file').write_text('source');(root/'dst').mkdir()
            files=ProjectFiles(root);proposal=files.directory_move_proposal('src','dst/new')
            def collision(source,destination):
                (root/'dst/new').mkdir();(root/'dst/new/user').write_text('keep')
                rename_directory_no_replace(source,destination)
            with patch('agentnik.directory_ops.rename_directory_no_replace',side_effect=collision),self.assertRaises(DirectoryMoveError):files.apply_directory_move(proposal)
            self.assertEqual((root/'dst/new/user').read_text(),'keep');self.assertEqual((root/'src/file').read_text(),'source')

    def test_posix_no_replace_calls_do_not_fall_back_to_overwrite(self):
        import agentnik.directory_ops as operations
        class NativeCall:
            def __init__(self,result):self.result=result;self.calls=[]
            def __call__(self,*args):self.calls.append(args);return self.result
        for platform in ('linux','darwin'):
            with self.subTest(platform=platform):
                native=NativeCall(-1);library=SimpleNamespace(**{('renameat2' if platform=='linux' else 'renamex_np'):native})
                with patch.object(operations,'os',SimpleNamespace(name='posix',fsencode=os.fsencode,strerror=os.strerror)),patch.object(operations,'sys',SimpleNamespace(platform=platform)),patch.object(operations.ctypes,'CDLL',return_value=library),patch.object(operations.ctypes,'get_errno',return_value=errno.EEXIST):
                    with self.assertRaises(FileExistsError):operations.rename_directory_no_replace('source','destination')
                self.assertEqual(len(native.calls),1);self.assertEqual(native.calls[0][-1],1 if platform=='linux' else 4)

    def test_nested_guidance_is_loaded_before_model_directory_move(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src/sub').mkdir(parents=True);(root/'dst').mkdir()
            (root/'src/sub/AGENTS.md').write_text('Nested project rules');(root/'src/sub/file').write_text('data')
            events=[];bodies=[];count=0
            def send(connection,url,body,timeout):
                nonlocal count
                bodies.append(json.loads(json.dumps(body)));count+=1
                if count<=2:return Wire(chat(calls=[call('move_directory',{'path':'src','destination':'dst/final'})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),folder,'Move directory').run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertIn('Nested project rules',json.dumps(bodies[1]));self.assertTrue((root/'dst/final/sub/file').exists())
            first=next(json.loads(m['content']) for m in bodies[1]['messages'] if m['role']=='tool');self.assertIn('guidance was loaded',first['error'])

    def test_model_renames_then_moves_directory_without_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src/sub').mkdir(parents=True);(root/'dst').mkdir();(root/'src/sub/a.bin').write_bytes(b'\x00\xff')
            events=[];bodies=[];count=0
            def send(connection,url,body,timeout):
                nonlocal count
                bodies.append(json.loads(json.dumps(body)));count+=1
                if count==1:return Wire(chat(calls=[call('rename_directory',{'path':'src','name':'renamed'}),call('move_directory',{'path':'renamed','destination':'dst/final'},'move')],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),folder,'Move directory').run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual((root/'dst/final/sub/a.bin').read_bytes(),b'\x00\xff')
            results=[json.loads(m['content']) for m in bodies[-1]['messages'] if m['role']=='tool']
            self.assertTrue(results[0]['applied']);self.assertTrue(results[1]['applied']);self.assertFalse(any(e['kind']=='operation_proposal' for e in events))

    def test_directory_rename_failure_stops_without_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src').mkdir();(root/'src/file').write_text('data');events=[]
            reply=Wire(chat(calls=[call('rename_directory',{'path':'src','name':'renamed'})],finish='tool_calls'),False)
            with patch.object(core,'open_request',return_value=reply) as endpoint,patch('agentnik.directory_ops.rename_directory_no_replace',side_effect=OSError('fixture')):
                CodingRun(dict(C,stream=False),folder,'Rename').run(events.append)
            self.assertEqual(endpoint.call_count,1);self.assertEqual(events[-1]['status'],'failed');self.assertIn('Inspect both paths',events[-1]['text'])
            self.assertTrue((root/'src/file').exists());self.assertFalse((root/'renamed').exists())

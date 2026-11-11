"""Project-contained file moves, conflict checks and model integration."""
import json
import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentnik import core
from agentnik.code_agent import CodingRun,MovePartialError,ProjectFiles
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire


class ProjectMove(unittest.TestCase):
    def test_snapshot_conflicts_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src').mkdir();(root/'dst').mkdir();source=root/'src/a.txt';source.write_text('original',encoding='utf-8')
            files=ProjectFiles(root)
            proposal=files.move_proposal('src/a.txt','dst/b.txt')
            (root/'dst/b.txt').write_text('user file',encoding='utf-8')
            with self.assertRaises(ValueError):files.apply_move(proposal)
            self.assertEqual(source.read_text(),'original');self.assertEqual((root/'dst/b.txt').read_text(),'user file')
            (root/'dst/b.txt').unlink();source.write_text('user edit',encoding='utf-8')
            with self.assertRaises(ValueError):files.apply_move(proposal)
            self.assertFalse((root/'dst/b.txt').exists());self.assertEqual(source.read_text(),'user edit')
            files.read('src/a.txt');files.apply_move(files.move_proposal('src/a.txt','dst/b.txt'))
            self.assertFalse(source.exists());self.assertEqual((root/'dst/b.txt').read_text(),'user edit')
            files.apply(files.proposal('dst/b.txt','after move'));self.assertEqual((root/'dst/b.txt').read_text(),'after move')

    def test_large_binary_moves_without_reading_contents_into_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'dst').mkdir();source=root/'data.bin';data=(b'\x00\xff\x80DATA'*500_000);source.write_bytes(data)
            events=[];bodies=[];count=0
            def send(connection,url,body,timeout):
                nonlocal count
                bodies.append(json.loads(json.dumps(body)));count+=1
                if count==1:return Wire(chat(calls=[call('rename_file',{'path':'data.bin','name':'renamed.bin'}),call('move_file',{'path':'renamed.bin','destination':'dst/result.bin'},'move')],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),folder,'Move binary').run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertFalse(source.exists());self.assertFalse((root/'renamed.bin').exists());self.assertEqual((root/'dst/result.bin').read_bytes(),data)
            self.assertNotIn('DATA',json.dumps(bodies));self.assertNotIn('DATA',json.dumps(events))

    def test_cross_filesystem_and_no_hardlink_fallback(self):
        for unsupported in (False,True):
            with self.subTest(no_hardlink=unsupported),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'dst').mkdir();source=root/'source.bin';data=b'\x00\xff'+os.urandom(2_100_000);source.write_bytes(data);original_mtime=source.stat().st_mtime_ns
                files=ProjectFiles(root);proposal=files.move_proposal('source.bin','dst/result.bin');original_link=os.link
                def link(src,dst,*args,**kwargs):
                    if Path(src)==source:raise OSError(errno.EXDEV,'different filesystem')
                    if unsupported:raise OSError(errno.EOPNOTSUPP,'hard links unsupported')
                    return original_link(src,dst,*args,**kwargs)
                with patch('agentnik.code_agent.os.link',side_effect=link):files.apply_move(proposal)
                self.assertFalse(source.exists());self.assertEqual((root/'dst/result.bin').read_bytes(),data);self.assertEqual((root/'dst/result.bin').stat().st_mtime_ns,original_mtime)
                self.assertFalse(list((root/'dst').glob('.agentnik-move-*')))

    def test_cross_filesystem_copy_cancellation_and_conflicts_leave_source(self):
        for scenario in ('cancel','change','collision'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'dst').mkdir();source=root/'source.bin';source.write_bytes(b'A'*2_500_000)
                target=root/'dst/result.bin';files=ProjectFiles(root);proposal=files.move_proposal('source.bin','dst/result.bin');checks=0
                def check():
                    nonlocal checks
                    checks+=1
                    if checks==4:
                        if scenario=='cancel':raise InterruptedError('cancelled')
                        if scenario=='change':source.write_bytes(b'user changed')
                        else:target.write_bytes(b'user destination')
                original_link=os.link
                def link(src,dst,*args,**kwargs):
                    if Path(src)==source:raise OSError(errno.EXDEV,'different filesystem')
                    return original_link(src,dst,*args,**kwargs)
                with patch('agentnik.code_agent.os.link',side_effect=link),self.assertRaises((InterruptedError,ValueError)):
                    files.apply_move(proposal,check)
                self.assertTrue(source.exists());self.assertEqual(target.read_bytes() if target.exists() else None,b'user destination' if scenario=='collision' else None)
                self.assertFalse(list((root/'dst').glob('.agentnik-move-*')))

    def test_exclusive_publish_without_hardlinks_and_cancel_cleanup(self):
        for scenario in ('success','cancel','collision'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'source.bin';data=b'\x00\xff'+os.urandom(2_100_000);source.write_bytes(data)
                staged=root/'staged.bin';staged.write_bytes(data);target=root/'target.bin';files=ProjectFiles(root);proposal=files.move_proposal('source.bin','target.bin');checks=0
                if scenario=='collision':target.write_bytes(b'user destination')
                def check():
                    nonlocal checks
                    checks+=1
                    if scenario=='cancel' and checks==2:raise InterruptedError('cancelled')
                if scenario=='success':
                    files.publish_move_copy(staged,target,proposal,check)
                    self.assertEqual(target.read_bytes(),data)
                else:
                    with self.assertRaises((InterruptedError,FileExistsError)):files.publish_move_copy(staged,target,proposal,check)
                    self.assertEqual(target.read_bytes() if target.exists() else None,b'user destination' if scenario=='collision' else None)
                self.assertEqual(source.read_bytes(),data)

    def test_replaced_staging_file_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'dst').mkdir();source=root/'source.bin';source.write_bytes(b'A'*2_500_000)
            files=ProjectFiles(root);proposal=files.move_proposal('source.bin','dst/result.bin');checks=0;replacement=[]
            def check():
                nonlocal checks
                checks+=1
                if checks==7:
                    staging=next((root/'dst').glob('.agentnik-move-*'));staging.rename(root/'dst/original-stage')
                    staging.write_bytes(b'user data');replacement.append(staging)
            original_link=os.link
            def link(src,dst,*args,**kwargs):
                if Path(src)==source:raise OSError(errno.EXDEV,'different filesystem')
                return original_link(src,dst,*args,**kwargs)
            with patch('agentnik.code_agent.os.link',side_effect=link),self.assertRaises(MovePartialError):files.apply_move(proposal,check)
            self.assertTrue(source.exists());self.assertFalse((root/'dst/result.bin').exists());self.assertEqual(replacement[0].read_bytes(),b'user data')

    def test_invalid_paths_directories_and_partial_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'a').write_text('text',encoding='utf-8');(root/'dir').mkdir();files=ProjectFiles(root);files.read('a')
            for target in ('../escape','.git/config','.env','dir','missing/child','a'):
                with self.subTest(target=target),self.assertRaises(ValueError):files.move_proposal('a',target)
            with self.assertRaises(ValueError):files.move_proposal('dir','newdir')
            proposal=files.move_proposal('a','b')
            with patch.object(Path,'unlink',side_effect=PermissionError('fixture')):
                with self.assertRaises(MovePartialError):files.apply_move(proposal)
            self.assertEqual((root/'a').read_text(),'text');self.assertEqual((root/'b').read_text(),'text')

    def test_rename_move_and_regex_tools_through_coding_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src').mkdir();(root/'dst').mkdir();(root/'src/a.py').write_text('def work():\n pass\n',encoding='utf-8')
            events=[];bodies=[];count=0
            def send(connection,url,body,timeout):
                nonlocal count
                bodies.append(json.loads(json.dumps(body)));count+=1
                if count==1:return Wire(chat(calls=[call('regex_search',{'path':'.','query':r'^def\s+\w+','pattern':'**/*.py','case_sensitive':'true'}),call('read_file',{'path':'src/a.py'},'read'),call('rename_file',{'path':'src/a.py','name':'renamed.py'},'rename'),call('move_file',{'path':'src/renamed.py','destination':'dst/final.py'},'move')],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),folder,'Refactor').run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual((root/'dst/final.py').read_text(),'def work():\n pass\n')
            self.assertFalse((root/'src/a.py').exists());self.assertFalse((root/'src/renamed.py').exists())
            self.assertFalse(any(event['kind'] in ('edit_proposal','operation_proposal') for event in events))
            results=[json.loads(m['content']) for m in bodies[-1]['messages'] if m['role']=='tool']
            self.assertEqual(results[0]['matches'][0]['line'],1);self.assertTrue(results[2]['applied']);self.assertTrue(results[3]['applied'])

    def test_destination_guidance_defers_move_until_heavy_sees_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src').mkdir();(root/'dst').mkdir();(root/'src/a.txt').write_text('text');(root/'dst/AGENTS.md').write_text('Destination rules')
            events=[];bodies=[];count=0
            def send(connection,url,body,timeout):
                nonlocal count
                bodies.append(json.loads(json.dumps(body)));count+=1
                if count==1:return Wire(chat(calls=[call('read_file',{'path':'src/a.txt'}),call('move_file',{'path':'src/a.txt','destination':'dst/a.txt'},'move')],finish='tool_calls'),False)
                if count==2:return Wire(chat(calls=[call('move_file',{'path':'src/a.txt','destination':'dst/a.txt'})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),folder,'Move').run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertIn('Destination rules',json.dumps(bodies[1]));self.assertTrue((root/'dst/a.txt').is_file())
            result=next(json.loads(m['content']) for m in bodies[1]['messages'] if m['role']=='tool' and m.get('tool_call_id')=='move')
            self.assertIn('guidance was loaded',result['error'])

    def test_cancellation_or_concurrent_edit_prevents_move(self):
        for scenario in ('cancel','change'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'a.txt';source.write_text('old',encoding='utf-8');events=[]
                replies=[Wire(chat(calls=[call('read_file',{'path':'a.txt'}),call('move_file',{'path':'a.txt','destination':'b.txt'},'move')],finish='tool_calls'),False),Wire(chat('Done'),False)]
                run=CodingRun(dict(C,stream=False),folder,'Move')
                def emit(event):
                    events.append(event)
                    if event.get('text','').startswith('Moving project file:'):
                        if scenario=='cancel':run.stop()
                        else:source.write_text('user edit',encoding='utf-8')
                with patch.object(core,'open_request',side_effect=replies):run.run(emit)
                self.assertFalse((root/'b.txt').exists());self.assertEqual(source.read_text(),'old' if scenario=='cancel' else 'user edit')

    def test_partial_move_stops_run_without_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'a.txt').write_text('text',encoding='utf-8');events=[]
            reply=Wire(chat(calls=[call('read_file',{'path':'a.txt'}),call('move_file',{'path':'a.txt','destination':'b.txt'},'move')],finish='tool_calls'),False)
            with patch.object(core,'open_request',return_value=reply) as endpoint,patch.object(Path,'unlink',side_effect=PermissionError('fixture')):
                CodingRun(dict(C,stream=False),folder,'Move').run(events.append)
            self.assertEqual(endpoint.call_count,1);self.assertEqual(events[-1]['status'],'failed');self.assertIn('Inspect both paths',events[-1]['text'])
            self.assertEqual((root/'a.txt').read_text(),'text');self.assertEqual((root/'b.txt').read_text(),'text')

"""Built-in bounded glob and literal grep tool behavior."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentnik import core
from agentnik.code_agent import CodingRun, ProjectFiles
from agentnik.code_search import glob_files,grep_files,glob_matcher
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire


class CodeSearch(unittest.TestCase):
    def test_glob_component_semantics_and_project_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src'/'nested').mkdir(parents=True)
            for name in ('main.py','README.md','src/main.py','src/nested/test_main.py','src/nested/notes.txt'):
                (root/name).write_text('sample',encoding='utf-8')
            files=ProjectFiles(root)
            self.assertEqual(glob_files(files,'.','*.py')['paths'],['main.py'])
            self.assertEqual(glob_files(files,'.','**/*.py')['paths'],['main.py','src/main.py','src/nested/test_main.py'])
            self.assertEqual(glob_files(files,'src','src/**/test_*.py')['paths'],['src/nested/test_main.py'])
            self.assertEqual(glob_files(files,'.',r'src\**\[mt]*.py')['paths'],['src/main.py','src/nested/test_main.py'])
            with self.assertRaises(ValueError):files.proposal('main.py','changed')
        for pattern in ('','../*.py','/tmp/*','C:/secret','foo/**bar','foo//bar','x'*257):
            with self.subTest(pattern=pattern),self.assertRaises(ValueError):glob_matcher(pattern)

    def test_grep_literal_filter_unicode_and_exclusions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'src').mkdir();(root/'.git').mkdir();(root/'.venv').mkdir()
            (root/'src'/'one.py').write_text('first\n'+('x'*150)+'Straße VALUE\n',encoding='utf-8')
            (root/'src'/'two.txt').write_text('STRASSE value',encoding='utf-8')
            (root/'.git'/'config').write_text('STRASSE value',encoding='utf-8')
            (root/'.venv'/'secret.py').write_text('STRASSE value',encoding='utf-8')
            (root/'binary.py').write_bytes(b'\x00STRASSE value')
            files=ProjectFiles(root);result=grep_files(files,'.','STRASSE','**/*.py','false')
            self.assertEqual([(m['path'],m['line']) for m in result['matches']],[('src/one.py',2)])
            self.assertIn('Straße VALUE',result['matches'][0]['text']);self.assertTrue(result['incomplete'])
            self.assertEqual(grep_files(files,'.','STRASSE','**/*.py','true')['matches'],[])
            self.assertNotIn('.git/config',glob_files(files,'.','**/*')['paths'])
            with self.assertRaises(ValueError):files.proposal('src/one.py','changed')
            for flag in ('yes','','False'):
                with self.assertRaises(ValueError):grep_files(files,'.','value','**/*',flag)

    def test_bounded_results_and_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i in range(110):(root/('file%03d.txt'%i)).write_text('match',encoding='utf-8')
            files=ProjectFiles(root)
            for result,key in ((glob_files(files,'.','**/*.txt'),'paths'),(grep_files(files,'.','match','**/*.txt','true'),'matches')):
                self.assertEqual(len(result[key]),100);self.assertTrue(result['incomplete'])
            def cancel():raise InterruptedError('cancelled')
            with self.assertRaises(InterruptedError):glob_files(files,'.','**/*',cancel)
            with self.assertRaises(InterruptedError):grep_files(files,'.','match','**/*','true',cancel)

    def test_hard_links_and_oversized_text_are_not_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.txt';source.write_text('match',encoding='utf-8')
            try:os.link(source,root/'linked.txt')
            except OSError:self.skipTest('Hard links unavailable on this filesystem')
            (root/'large.txt').write_text('match'+'x'*2_000_000,encoding='utf-8')
            files=ProjectFiles(root);result=grep_files(files,'.','match','**/*.txt','true')
            self.assertEqual(result['matches'],[]);self.assertTrue(result['incomplete'])
            self.assertEqual(glob_files(files,'.','**/*.txt')['paths'],['large.txt'])

    def test_coding_loop_exposes_tools_and_scrubs_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'one.py').write_text('Needle secret-token',encoding='utf-8')
            bodies=[];events=[];count=0
            def send(connection,url,body,timeout):
                nonlocal count
                bodies.append(json.loads(json.dumps(body)));count+=1
                if count==1:return Wire(chat(calls=[call('glob_files',{'path':'.','pattern':'**/*.py'}),call('grep_files',{'path':'.','query':'needle','pattern':'**/*.py','case_sensitive':'false'},'grep')],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False,api_key='secret-token'),folder,'Find code').run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events)
            self.assertIn('glob_files',json.dumps(bodies[0]['tools']));self.assertIn('grep_files',json.dumps(bodies[0]['tools']))
            results=[json.loads(m['content']) for m in bodies[-1]['messages'] if m['role']=='tool']
            self.assertEqual(results[0]['paths'],['one.py']);self.assertIn('[redacted]',results[1]['matches'][0]['text'])
            self.assertNotIn('secret-token',json.dumps(events)+json.dumps(bodies))

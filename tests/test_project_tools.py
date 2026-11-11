import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles,CodingRun
from agentnik.project_tools import ProjectTools,ProjectToolError
from agentnik.test_reports import parse_report
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire


class ProjectInspection(unittest.TestCase):
    def test_patch_diff_marks_missing_final_newlines(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'file.txt';path.write_bytes(b'old')
            files=ProjectFiles(Path(folder));files.read('file.txt')
            diff=ProjectTools(files).patch('file.txt','old','new')['diff']
            self.assertIn('-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n',diff)

    def test_expanded_full_reads_writes_and_large_range_patches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);small=root/'full.txt';small.write_text('a'*100_000,encoding='utf-8')
            files=ProjectFiles(root);self.assertEqual(len(files.read('full.txt')),100_000)
            files.apply(files.proposal('full.txt','b'*120_000));self.assertEqual(small.stat().st_size,120_000)
            large=root/'large.txt';large.write_bytes((b'x'*100+b'\n')*11000+b'target unique\n'+(b'x'*100+b'\n')*11000)
            self.assertGreater(large.stat().st_size,2_000_000);tools=ProjectTools(files)
            view=tools.read_range('large.txt','11001','11001');self.assertEqual(view['lines'][0]['text'],'target unique\n')
            files.apply(tools.patch('large.txt','target unique','replacement'))
            self.assertIn(b'replacement',large.read_bytes())

    def test_larger_range_and_patch_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'large-line.txt';path.write_bytes(('prefix\n'+'a'*50_000+'\nsuffix\n').encode('utf-8'))
            files=ProjectFiles(root);tools=ProjectTools(files);view=tools.read_range('large-line.txt','1','3')
            self.assertFalse(view['truncated']);self.assertEqual(len(view['lines'][1]['text']),50_001)
            proposal=tools.patch('large-line.txt','a'*50_000,'b'*50_000);self.assertIn('@@ -2 +2 @@',proposal['diff'])
            files.apply(proposal);self.assertEqual(path.read_text(), 'prefix\n'+'b'*50_000+'\nsuffix\n')

    def test_expanded_text_capacity_through_model_tool_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.txt';path.write_text('a'*90_000,encoding='utf-8');events=[];bodies=[];count=0
            def send(connection,url,body,timeout):
                nonlocal count
                bodies.append(json.loads(json.dumps(body)));count+=1
                if count==1:return Wire(chat(calls=[call('read_file',{'path':'source.txt'})],finish='tool_calls'),False)
                if count==2:return Wire(chat(calls=[call('write_file',{'path':'source.txt','content':'b'*100_000})],finish='tool_calls'),False)
                return Wire(chat('Done'),False)
            with patch('agentnik.core.open_request',side_effect=send):CodingRun(dict(C,stream=False),folder,'Update').run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);self.assertEqual(path.read_text(), 'b'*100_000)
            result=next(json.loads(m['content']) for m in bodies[1]['messages'] if m['role']=='tool')
            self.assertEqual(len(result['text']),90_000)

    def test_large_range_patch_preserves_other_lines_and_rejects_changed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'large.py';raw=b''.join(('line '+str(i)+'\r\n').encode() for i in range(10000));path.write_bytes(raw)
            files=ProjectFiles(folder);tools=ProjectTools(files)
            result=tools.read_range('large.py','4999','5003');self.assertEqual(result['lines'][0]['line'],4999)
            with self.assertRaises(ValueError):files.proposal('large.py','replace unseen file')
            proposal=tools.patch('large.py','line 5000\r\n','changed 5000\r\n')
            self.assertIn('-line 5000',proposal['diff']);self.assertEqual(path.read_bytes(),raw)
            path.write_bytes(raw+b'external edit')
            with self.assertRaises(ValueError):files.apply(proposal)
            path.write_bytes(raw);files.apply(proposal)
            self.assertEqual(path.read_bytes(),raw.replace(b'line 5000\r\n',b'changed 5000\r\n'))
            with self.assertRaises(ProjectToolError):tools.patch('large.py','changed 5000','another change')

    def test_patch_requires_unique_seen_current_text_and_checks_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'small.py';path.write_bytes(b'first\nrepeat\nrepeat\nlast\n');files=ProjectFiles(folder);tools=ProjectTools(files)
            tools.read_range('small.py','1','2')
            for old in ('repeat','last','missing'):
                with self.assertRaises(ProjectToolError):tools.patch('small.py',old,'replacement')
            proposal=tools.patch('small.py','first','new')
            def cancelled():raise InterruptedError()
            with self.assertRaises(InterruptedError):files.apply(proposal,cancelled)
            self.assertTrue(path.read_bytes().startswith(b'first'))
            self.assertEqual(list(Path(folder).glob('.agentnik-edit-*')),[])
            tools.read_range('small.py','3','4');proposal=tools.patch('small.py','repeat\nlast','repeat\nend');files.apply(proposal)
            self.assertTrue(path.read_bytes().endswith(b'end\n'))

    def test_range_budgets_and_exclusions(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'code.txt';path.write_text(('x'*500+'\n')*180)
            tools=ProjectTools(ProjectFiles(folder));result=tools.read_range('code.txt','1','180')
            self.assertTrue(result['truncated']);self.assertLess(result['end_line'],180);self.assertEqual(result['next_line'],result['end_line']+1)
            for start,end in (('0','1'),('-1','1'),('1','1001'),('2','1'),('999','999')):
                with self.assertRaises(ValueError):tools.read_range('code.txt',start,end)
            for path in ('../outside','.env','.git/config'):
                with self.assertRaises(ValueError):tools.read_range(path,'1','2')
            Path(folder,'binary').write_bytes(b'hello\n\x00')
            with self.assertRaises(ValueError):tools.read_range('binary','1','1')

    def test_overview_reads_metadata_without_running_it_or_exposing_specs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'tests').mkdir();(root/'main.py').write_text('print(1)')
            (root/'.env').write_text('secret');(root/'pyproject.toml').write_text('[project]\ndependencies=["requests>=2"]\n[project.scripts]\nhello="module:main"\n')
            (root/'package.json').write_text(json.dumps({'dependencies':{'react':'https://private.example/token'},'scripts':{'test':'a command that must not execute'}}))
            with patch('subprocess.Popen',side_effect=AssertionError('Metadata must not execute')):
                result=ProjectTools(ProjectFiles(folder)).overview()
            self.assertEqual(result['dependency_names'],['react','requests']);self.assertIn('Python',result['languages']);self.assertIn('tests/',result['test_configuration'])
            self.assertIn('hello',result['script_or_entry_point_names']);self.assertNotIn('private.example',json.dumps(result));self.assertNotIn('.env',result['sample_files'])


class TestReports(unittest.TestCase):
    def test_known_frameworks_report_counts(self):
        cases=[('Ran 5 tests in 0.1s\n\nFAILED (failures=1, errors=1, skipped=1)\n',1,'unittest',5,1),('=== 1 failed, 2 passed, 1 skipped in 0.20s ===',1,'pytest',4,1),('Tests: 1 failed, 2 passed, 3 total',1,'jest',3,1),(' Tests  2 passed (2)',0,'vitest',2,0)]
        for text,code,format,total,failed in cases:
            with self.subTest(format=format):
                report=parse_report({'output':text,'exit_code':code,'truncated':False})
                self.assertEqual(report['format'],format);self.assertEqual(report['counts']['total'],total);self.assertEqual(report['counts']['failed'],failed)
        self.assertEqual(parse_report({'output':cases[0][0],'exit_code':1})['counts']['errors'],1)

    def test_unrecognized_or_truncated_success_is_not_claimed_verified(self):
        for text,truncated in [('hello',False),('Ran 2 tests in 0.1s\nOK\n',True)]:
            report=parse_report({'output':text,'exit_code':0,'truncated':truncated})
            self.assertEqual(report['outcome'],'unknown')
        report=parse_report({'output':'command not found','exit_code':127,'truncated':False})
        self.assertEqual(report['outcome'],'failed');self.assertIsNone(report['counts']['passed'])
        for output in ('  ● example suite\nExpected true, received false',' FAIL tests/example.test.ts\nAssertionError: mismatch'):
            self.assertTrue(parse_report({'output':output,'exit_code':1,'truncated':False})['failures'])


class ModelToolIntegration(unittest.TestCase):
    def test_patch_applies_without_approval_and_preserves_surrounding_text(self):
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'code.py';path.write_bytes(b'before\ntarget\nafter\n');events=[]
                replies=[Wire(chat(calls=[call('read_file_range',{'path':'code.py','start_line':'2','end_line':'2'}),call('apply_patch',{'path':'code.py','old_text':'target','new_text':'replacement'},'patch')],finish='tool_calls'),False),Wire(chat('Done'),False)]
                run=CodingRun(dict(C,stream=False),folder,'Patch one line')
                def emit(event):
                    events.append(event)
                with patch('agentnik.core.open_request',side_effect=replies):run.run(emit)
                self.assertEqual(path.read_bytes(),b'before\nreplacement\nafter\n');self.assertEqual(events[-1]['status'],'completed');self.assertFalse(any(e['kind']=='edit_proposal' for e in events))

    def test_test_command_requires_approval_and_returns_structured_counts(self):
        for allow in (False,True):
            with self.subTest(allow=allow),tempfile.TemporaryDirectory() as folder:
                replies=[Wire(chat(calls=[call('run_tests',{'path':'.','command':'python -m unittest','format':'auto'})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[]
                run=CodingRun(dict(C,stream=False),folder,'Run tests')
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                def emit(event):
                    events.append(event)
                    if event['kind']=='operation_proposal':
                        self.assertEqual(event['proposal']['purpose'],'tests');run.decide(event['fingerprint'],allow)
                with patch('agentnik.core.open_request',side_effect=send),patch('agentnik.shell.execute',return_value={'exit_code':0,'output':'Ran 3 tests in 0.1s\nOK\n','truncated':False}) as execute:
                    run.run(emit);self.assertEqual(execute.call_count,int(allow))
                self.assertEqual(events[-1]['status'],'completed')
                if allow:
                    report=json.loads(bodies[1]['messages'][-1]['content'])['test_report'];self.assertEqual(report['counts']['passed'],3);self.assertEqual(report['outcome'],'passed')

    def test_approved_native_unittest_command_returns_real_summary(self):
        import os,sys,shlex
        with tempfile.TemporaryDirectory() as folder:
            tests=Path(folder)/'tests';tests.mkdir();(tests/'test_example.py').write_text('import unittest\nclass Example(unittest.TestCase):\n    def test_ok(self): self.assertEqual(2 + 2, 4)\n')
            executable=sys.executable
            command=("& '"+executable.replace("'","''")+"' -m unittest discover -s tests -v") if os.name=='nt' else shlex.quote(executable)+' -m unittest discover -s tests -v'
            replies=[Wire(chat(calls=[call('run_tests',{'path':'.','command':command,'format':'unittest'})],finish='tool_calls'),False),Wire(chat('Tests passed'),False)];events=[];bodies=[]
            run=CodingRun(dict(C,stream=False),folder,'Run the temporary test')
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch('agentnik.core.open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed')
            report=json.loads(bodies[1]['messages'][-1]['content'])['test_report']
            self.assertEqual(report['counts']['total'],1);self.assertEqual(report['outcome'],'passed')

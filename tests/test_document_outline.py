import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles,CodingRun
from agentnik.document_outline import document_outline
from agentnik.project_tools import ProjectToolError,ProjectTools
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

class DocumentOutlines(unittest.TestCase):
    def test_markdown_headings_fences_frontmatter_and_section_ranges(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'guide.md';path.write_text('---\ntitle: example\n# front matter comment\n---\n# Top\ntext\n## Child\n```python\n# not heading\n```\nNext heading\n------------\n# Last\n',encoding='utf-8')
            files=ProjectFiles(folder);result=document_outline(files,'guide.md')
            self.assertEqual([(x['title'],x['level'],x['line'],x['end_line']) for x in result['entries']],[('Top',1,5,12),('Child',2,7,10),('Next heading',2,11,12),('Last',1,13,13)])
            self.assertFalse(result['incomplete']);self.assertFalse(files.observed)
            with self.assertRaises(ValueError):files.proposal('guide.md','new')
            with self.assertRaises(ProjectToolError):ProjectTools(files).patch('guide.md','# Top','# New')

    def test_json_key_paths_arrays_and_pointer_escaping(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'config.json').write_text('{\n  "a/b": {"~key": 2},\n  "items": [{"name": "one"}, {"name": "two"}]\n}',encoding='utf-8')
            result=document_outline(ProjectFiles(folder),'config.json')
            self.assertEqual([x['path'] for x in result['entries']],['/a~1b','/a~1b/~0key','/items','/items/0/name','/items/1/name'])
            self.assertEqual(result['entries'][0]['line'],2);self.assertFalse(result['incomplete'])

    def test_yaml_multiple_documents_alias_and_untrusted_tags(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'config.yaml').write_text('defaults: &defaults\n  retries: 3\ncopy: *defaults\n---\nvalue: !custom no_execution\n',encoding='utf-8')
            result=document_outline(ProjectFiles(folder),'config.yaml');self.assertEqual([(x['document'],x['path'],x['value_type']) for x in result['entries']],[(1,'/defaults','mapping'),(1,'/defaults/retries','scalar'),(1,'/copy','alias'),(2,'/value','scalar')]);self.assertTrue(result['incomplete'])

    def test_invalid_paths_json_and_output_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'bad.json').write_text('{invalid}',encoding='utf-8');(root/'bad.yaml').write_text('a: [unclosed',encoding='utf-8');(root/'.env.yaml').write_text('secret: 1',encoding='utf-8');(root/'many.json').write_text(json.dumps({str(i):i for i in range(200)}),encoding='utf-8')
            files=ProjectFiles(folder)
            for name in ('bad.json','bad.yaml','.env.yaml','../outside.yaml','foo.py'):
                with self.subTest(name=name),self.assertRaises((ValueError,ProjectToolError)):document_outline(files,name)
            result=document_outline(files,'many.json');self.assertTrue(result['incomplete']);self.assertEqual(len(result['entries']),150)
            with self.assertRaises(InterruptedError):document_outline(files,'many.json',lambda:(_ for _ in ()).throw(InterruptedError()))

    def test_yaml_complex_keys_cycles_and_json_surrogate_are_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'complex.yaml').write_text('? [one, two]\n: value\ncycle: &node\n  self: *node\n',encoding='utf-8')
            (root/'surrogate.json').write_text('{"\\ud800": 1}',encoding='utf-8')
            files=ProjectFiles(folder);result=document_outline(files,'complex.yaml')
            self.assertTrue(result['incomplete']);self.assertLess(len(result['entries']),10)
            result=document_outline(files,'surrogate.json');self.assertEqual(len(result['entries']),1)

    def test_model_tool_then_range_read(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'readme.md').write_text('# Heading\nText\n',encoding='utf-8')
            replies=[Wire(chat(calls=[call('document_outline',{'path':'readme.md'})],finish='tool_calls'),False),Wire(chat(calls=[call('read_file_range',{'path':'readme.md','start_line':'1','end_line':'2'})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[]
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.core.open_request',side_effect=request):CodingRun(dict(C,stream=False),folder,'Inspect').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');tool=next(json.loads(m['content']) for m in bodies[1]['messages'] if m.get('role')=='tool');self.assertEqual(tool['entries'][0]['title'],'Heading');self.assertIn('Text',json.dumps(bodies[2]))

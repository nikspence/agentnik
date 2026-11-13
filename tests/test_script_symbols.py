"""JavaScript and TypeScript syntax outline coverage."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik.code_agent import ProjectFiles,CodingRun
from agentnik.script_symbols import script_outline
from agentnik.project_tools import ProjectToolError,ProjectTools
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

class ScriptOutlines(unittest.TestCase):
    def test_four_languages_and_precise_lines(self):
        fixtures={
            'app.js':('export function hello() {\n return 1;\n}\nclass Box { open() {} }\nconst obj = { arrow: () => 1 };\n',['hello','Box','Box.open','obj','obj.arrow']),
            'app.jsx':('export const Card = () => <div>Hi</div>;\n',['Card']),
            'app.ts':('export interface Data { run(): void }\nexport type Item = string;\nexport enum Kind { A }\nexport function go(x: Item): void {}\n',['Data','Data.run','Item','Kind','go']),
            'app.tsx':('interface Props { label: string }\nexport const Card = ({label}: Props) => <div>{label}</div>;\n',['Props','Card'])}
        with tempfile.TemporaryDirectory() as root:
            for name,(text,expected) in fixtures.items():
                with self.subTest(name=name):
                    (Path(root)/name).write_text(text,encoding='utf-8');files=ProjectFiles(root);value=script_outline(files,name)
                    self.assertEqual([item['name'] for item in value['symbols']],expected);self.assertFalse(value['syntax_errors']);self.assertFalse(value['incomplete'])
                    self.assertEqual(value['symbols'][0]['line'],1);self.assertEqual(files.observed,{})
                    with self.assertRaises(ValueError):files.proposal(name,'replacement')
                    with self.assertRaises(ProjectToolError):ProjectTools(files).patch(name,'export','other')

    def test_unicode_incomplete_syntax_exclusions_and_bounds(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);(root/'unicode.ts').write_text('export function café() { return 1; }\n',encoding='utf-8');(root/'broken.js').write_text('function first() {}\nfunction broken( {',encoding='utf-8');(root/'.env.js').write_text('const x=1;',encoding='utf-8');(root/'many.js').write_text('\n'.join('function f%d() {}'%i for i in range(180)),encoding='utf-8')
            files=ProjectFiles(root);self.assertEqual(script_outline(files,'unicode.ts')['symbols'][0]['name'],'café')
            broken=script_outline(files,'broken.js');self.assertTrue(broken['syntax_errors']);self.assertTrue(broken['incomplete']);self.assertIn('first',[x['name'] for x in broken['symbols']])
            many=script_outline(files,'many.js');self.assertTrue(many['incomplete']);self.assertEqual(len(many['symbols']),150)
            for path in ('.env.js','../outside.js','unicode.py'):
                with self.subTest(path=path),self.assertRaises((ValueError,ProjectToolError)):script_outline(files,path)
            def cancel():raise InterruptedError('cancelled')
            with self.assertRaises(InterruptedError):script_outline(files,'unicode.ts',cancel)

    def test_model_tool_call_returns_outline(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'main.tsx').write_text('export const App = () => <main>Hello</main>;\n',encoding='utf-8')
            replies=[Wire(chat(calls=[call('script_outline',{'path':'main.tsx'})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[]
            def request(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with patch('agentnik.core.open_request',side_effect=request):CodingRun(dict(C,stream=False),root,'Inspect').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');result=next(json.loads(m['content']) for m in bodies[1]['messages'] if m.get('role')=='tool');self.assertEqual(result['symbols'][0]['name'],'App');self.assertEqual(result['symbols'][0]['kind'],'function');self.assertTrue(result['symbols'][0]['exported'])

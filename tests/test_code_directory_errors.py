import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agentnik import core
from agentnik.code_agent import CodingRun
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire

class DirectoryErrors(unittest.TestCase):
    def test_missing_directory_returns_helpful_tool_result_and_continues(self):
        with tempfile.TemporaryDirectory() as root:
            events=[];bodies=[]
            replies=[Wire(chat(calls=[call('list_files',{'path':'assets'})],finish='tool_calls'),False),Wire(chat('The directory is missing.'),False)]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect').run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertIn('Directory does not exist in the selected project',json.dumps(bodies[1]));self.assertIn('List the parent directory',json.dumps(bodies[1]))
            self.assertTrue(any('Directory does not exist' in event.get('text','') for event in events))

    def test_file_path_has_specific_feedback(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'a.txt').write_text('text');bodies=[]
            replies=[Wire(chat(calls=[call('list_files',{'path':'a.txt'},'a')],finish='tool_calls'),False),Wire(chat('Done'),False)]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect').run(lambda _:None)
            value=json.dumps(bodies[1]);self.assertIn('Path is not a directory',value)

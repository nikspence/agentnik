import unittest

from agentnik.mcp_completion import completion_params, parse_completion


class MCPCompletionTests(unittest.TestCase):
    def test_prompt_and_resource_references(self):
        prompt={'name':'review','arguments':[{'name':'language'},{'name':'file'}]}
        self.assertEqual(completion_params('prompt',prompt,'file','ma',{'language':'python'}), {
            'ref':{'type':'ref/prompt','name':'review'},
            'argument':{'name':'file','value':'ma'},
            'context':{'arguments':{'language':'python'}}})
        template={'uriTemplate':'test://{item}','supported':True}
        self.assertEqual(completion_params('resource',template,'item','a',{}), {
            'ref':{'type':'ref/resource','uri':'test://{item}'},
            'argument':{'name':'item','value':'a'}})

    def test_invalid_arguments_and_responses_are_rejected(self):
        prompt={'name':'review','arguments':[{'name':'file'}]}
        for argument,value,context in [('unknown','',{}),('file','',{'other':'x'}),('file','x'*16001,{}),('file',1,{})]:
            with self.subTest(argument=argument,context=context):
                with self.assertRaises(ValueError):completion_params('prompt',prompt,argument,value,context)
        for completion in ({'values':['x']*101},{'values':[3]},{'values':[],'total':True},{'values':[],'hasMore':'yes'}):
            with self.subTest(completion=completion):
                with self.assertRaises(ValueError):parse_completion({'completion':completion})
        self.assertEqual(parse_completion({'completion':{'values':['one'],'total':2,'hasMore':True,'ignored':'x'}}),{'values':['one'],'total':2,'hasMore':True})

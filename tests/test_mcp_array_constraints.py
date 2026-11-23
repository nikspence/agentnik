import time
import unittest
from agentnik.mcp_schema import MCPArgumentValidationError,validate_tool_arguments,validate_tool_result


class ArrayConstraintTests(unittest.TestCase):
    def test_contains_with_minimum_and_maximum(self):
        schema={'type':'object','properties':{'values':{'type':'array','contains':{'type':'integer','minimum':10},'minContains':1,'maxContains':2}}}
        for values in ([10],[1,10,20],[10,'other']):self.assertTrue(validate_tool_arguments(schema,{'values':values}))
        for values in ([],[1,2],[10,11,12]):
            with self.subTest(values=values),self.assertRaises(MCPArgumentValidationError) as caught:validate_tool_arguments(schema,{'values':values})
            self.assertIn('matching items',str(caught.exception))
        zero={'type':'object','properties':{'values':{'type':'array','contains':{'const':'x'},'minContains':0,'maxContains':0}}}
        self.assertTrue(validate_tool_arguments(zero,{'values':['y']}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(zero,{'values':['x']})
        tool={'output_schema_status':'available','output_schema':schema}
        with self.assertRaises(ValueError):validate_tool_result(tool,{'structuredContent':{'values':[1,2]}})

    def test_draft7_contains_and_dialect_validation(self):
        schema={'$schema':'http://json-schema.org/draft-07/schema#','type':'object','properties':{'values':{'type':'array','contains':{'const':'x'}}}}
        self.assertTrue(validate_tool_arguments(schema,{'values':['a','x']}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'values':['a']})
        schema['properties']['values']['minContains']=0
        with self.assertRaises(ValueError):validate_tool_arguments(schema,{'values':[]})
        for count in (-1,'one',True):
            invalid={'type':'object','properties':{'values':{'contains':True,'minContains':count}}}
            with self.subTest(count=count),self.assertRaises(ValueError):validate_tool_arguments(invalid,{})

    def test_negation_and_local_references(self):
        schema={'type':'object','$defs':{'blocked':{'const':'private-secret'}},'properties':{'name':{'type':'string','not':{'$ref':'#/$defs/blocked'}},'alias':{'$ref':'#/properties/name/not'}}}
        self.assertTrue(validate_tool_arguments(schema,{'name':'allowed','alias':'private-secret'}))
        with self.assertRaises(MCPArgumentValidationError) as caught:validate_tool_arguments(schema,{'name':'private-secret'})
        self.assertNotIn('private-secret',str(caught.exception));self.assertIn('prohibited',str(caught.exception))
        self.assertTrue(validate_tool_arguments({'type':'object','not':False},{}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments({'type':'object','not':True},{})
        with self.assertRaises(ValueError):validate_tool_arguments({'type':'object','not':{'$ref':'#/not'}},{})
        with self.assertRaises(ValueError):validate_tool_arguments({'type':'object','properties':{'x':{'contains':{'$ref':'#/properties/x/contains'}}}},{})
        contains_ref={'type':'object','$defs':{'desired':{'type':'integer','minimum':2}},'properties':{'values':{'type':'array','contains':{'$ref':'#/$defs/desired'}},'copy':{'$ref':'#/properties/values/contains'}}}
        self.assertTrue(validate_tool_arguments(contains_ref,{'values':[1,2],'copy':3}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(contains_ref,{'values':[1]})

    def test_contains_pattern_matching_is_time_bounded(self):
        schema={'type':'object','properties':{'values':{'type':'array','contains':{'pattern':'^(a+)+$'}}}};start=time.monotonic()
        with self.assertRaises(ValueError):validate_tool_arguments(schema,{'values':['a'*10000+'!']})
        self.assertLess(time.monotonic()-start,2)


if __name__=='__main__':unittest.main()

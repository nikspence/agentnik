import time
import unittest
from agentnik.mcp_schema import MCPArgumentValidationError,validate_tool_arguments,validate_tool_result


class ConditionalSchemaTests(unittest.TestCase):
    def test_conditional_branches_and_boolean_schemas(self):
        for dialect in (None,'http://json-schema.org/draft-07/schema#'):
            with self.subTest(dialect=dialect):
                schema={'type':'object','properties':{'mode':{'enum':['id','text']},'identifier':{'type':'integer'},'query':{'type':'string'}},'required':['mode'],'if':{'properties':{'mode':{'const':'id'}},'required':['mode']},'then':{'required':['identifier']},'else':{'required':['query']}}
                if dialect:schema['$schema']=dialect
                self.assertTrue(validate_tool_arguments(schema,{'mode':'id','identifier':4}))
                self.assertTrue(validate_tool_arguments(schema,{'mode':'text','query':'find'}))
                for invalid in ({'mode':'id','query':'private-secret'},{'mode':'text','identifier':7}):
                    with self.assertRaises(MCPArgumentValidationError) as caught:validate_tool_arguments(schema,invalid)
                    self.assertNotIn('private-secret',str(caught.exception))
                tool={'output_schema_status':'available','output_schema':schema}
                self.assertTrue(validate_tool_result(tool,{'structuredContent':{'mode':'id','identifier':4}}))
                with self.assertRaises(ValueError):validate_tool_result(tool,{'structuredContent':{'mode':'id'}})
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments({'type':'object','if':True,'then':False},{})
        self.assertTrue(validate_tool_arguments({'type':'object','if':False,'then':False,'else':True},{}))

    def test_dialect_specific_dependency_rules(self):
        modern={'type':'object','dependentRequired':{'start':['end']},'dependentSchemas':{'secure':{'required':['token']}}}
        legacy={'$schema':'http://json-schema.org/draft-07/schema#','type':'object','dependencies':{'start':['end'],'secure':{'required':['token']}}}
        for schema in (modern,legacy):
            with self.subTest(schema=schema):
                self.assertTrue(validate_tool_arguments(schema,{'start':1,'end':2,'secure':True,'token':'present'}))
                self.assertTrue(validate_tool_arguments(schema,{}))
                for invalid in ({'start':1},{'secure':True}):
                    with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,invalid)
                with self.assertRaises(MCPArgumentValidationError) as caught:validate_tool_arguments(schema,{'start':1})
                self.assertIn('end',str(caught.exception));self.assertIn('dependent field',str(caught.exception))
        for invalid in ({'type':'object','dependencies':{'x':['y']}},{'$schema':'http://json-schema.org/draft-07/schema#','type':'object','dependentRequired':{'x':['y']}},{'type':'object','dependentRequired':{'x':'y'}},{'type':'object','dependentSchemas':{'x':['y']}}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):validate_tool_arguments(invalid,{})

    def test_references_cycles_and_condition_complexity(self):
        schema={'type':'object','if':{'properties':{'kind':{'const':'short'}}},'then':{'properties':{'value':{'type':'string','minLength':2}}},'properties':{'copy':{'$ref':'#/then/properties/value'}}}
        self.assertTrue(validate_tool_arguments(schema,{'kind':'short','value':'ok','copy':'ok'}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'kind':'short','copy':'x'})
        dependency_ref={'type':'object','dependentSchemas':{'flag':{'required':['needed']}},'properties':{'copy':{'$ref':'#/dependentSchemas/flag'}}}
        self.assertTrue(validate_tool_arguments(dependency_ref,{'copy':{'needed':True}}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(dependency_ref,{'copy':{}})
        for invalid in ({'type':'object','if':{'$ref':'#/if'}},{'type':'object','dependentSchemas':{'x':{'$ref':'#/dependentSchemas/x'}}}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):validate_tool_arguments(invalid,{})
        nested={'type':'object'};current=nested
        for _ in range(6):current['if']={};current['then']={};current=current['then']
        with self.assertRaises(ValueError):validate_tool_arguments(nested,{})

    def test_condition_patterns_remain_time_bounded(self):
        schema={'type':'object','if':{'properties':{'value':{'pattern':'^(a+)+$'}}},'then':{'required':['x']}};start=time.monotonic()
        with self.assertRaises(ValueError):validate_tool_arguments(schema,{'value':'a'*10000+'!'})
        self.assertLess(time.monotonic()-start,2)


if __name__=='__main__':unittest.main()

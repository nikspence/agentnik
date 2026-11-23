import time
import unittest
from agentnik.mcp_schema import MCPArgumentValidationError,validate_tool_arguments,validate_tool_result


class PropertyNamesTests(unittest.TestCase):
    def test_constrained_dictionary_keys_in_both_dialects(self):
        for dialect in (None,'http://json-schema.org/draft-07/schema#'):
            with self.subTest(dialect=dialect):
                schema={'type':'object','properties':{'metrics':{'type':'object','propertyNames':{'minLength':3,'maxLength':8},'additionalProperties':{'type':'integer'}}}}
                if dialect:schema['$schema']=dialect
                self.assertTrue(validate_tool_arguments(schema,{'metrics':{'count':2,'total':3}}))
                for value in ({'metrics':{'x':1}},{'metrics':{'secret-key':1}},{'metrics':{'count':'bad'}}):
                    with self.subTest(value=value),self.assertRaises(MCPArgumentValidationError) as caught:validate_tool_arguments(schema,value)
                    self.assertNotIn('secret-key',str(caught.exception));self.assertNotIn('bad',str(caught.exception))
                tool={'output_schema_status':'available','output_schema':schema}
                self.assertTrue(validate_tool_result(tool,{'structuredContent':{'metrics':{'count':2}}}))
                with self.assertRaises(ValueError):validate_tool_result(tool,{'structuredContent':{'metrics':{'x':2}}})

    def test_property_name_subschemas_references_and_boolean_forms(self):
        schema={'type':'object','$defs':{'name':{'type':'string','minLength':2}},'propertyNames':{'$ref':'#/$defs/name'}}
        self.assertTrue(validate_tool_arguments(schema,{'ok':1}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'x':1})
        ref={'type':'object','propertyNames':{'type':'string','minLength':2},'properties':{'copy':{'$ref':'#/propertyNames'}}}
        self.assertTrue(validate_tool_arguments(ref,{'copy':'ok'}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(ref,{'copy':'x'})
        self.assertTrue(validate_tool_arguments({'type':'object','propertyNames':False},{}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments({'type':'object','propertyNames':False},{'x':1})
        with self.assertRaises(ValueError):validate_tool_arguments({'type':'object','propertyNames':{'$ref':'#/propertyNames'}},{})

    def test_expensive_property_name_pattern_is_time_bounded(self):
        schema={'type':'object','propertyNames':{'pattern':'^(a+)+$'}};start=time.monotonic()
        with self.assertRaises(ValueError):validate_tool_arguments(schema,{'a'*10000+'!':1})
        self.assertLess(time.monotonic()-start,2)


if __name__=='__main__':unittest.main()

import time
import unittest
from agentnik.mcp_schema import MCPArgumentValidationError,validate_tool_arguments,validate_tool_result


class PatternPropertiesTests(unittest.TestCase):
    def test_patterns_and_named_properties_compose_in_both_dialects(self):
        for dialect in (None,'http://json-schema.org/draft-07/schema#'):
            with self.subTest(dialect=dialect):
                schema={'type':'object','properties':{'fixed':{'type':'integer'}},'patternProperties':{'^x-':{'type':'string'},'-id$':{'minLength':3}},'additionalProperties':False}
                if dialect:schema['$schema']=dialect
                self.assertTrue(validate_tool_arguments(schema,{'fixed':1,'x-name':'ok','x-id':'abc'}))
                for value in ({'fixed':1,'x-id':'a'},{'fixed':1,'x-name':2},{'fixed':1,'private-key':'secret'}):
                    with self.subTest(value=value),self.assertRaises(MCPArgumentValidationError) as caught:validate_tool_arguments(schema,value)
                    self.assertNotIn('secret',str(caught.exception));self.assertNotIn('private-key',str(caught.exception))

    def test_additional_schema_applies_only_to_unmatched_keys(self):
        schema={'type':'object','properties':{'name':{'type':'string'}},'patternProperties':{'^flag_':{'type':'boolean'}},'additionalProperties':{'type':'integer'}}
        self.assertTrue(validate_tool_arguments(schema,{'name':'demo','flag_a':True,'other':2}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'flag_a':'wrong'})
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'other':'wrong'})
        tool={'output_schema_status':'available','output_schema':schema}
        self.assertTrue(validate_tool_result(tool,{'structuredContent':{'flag_a':True,'other':2}}))
        with self.assertRaisesRegex(ValueError,'structured result'):validate_tool_result(tool,{'structuredContent':{'flag_a':'wrong'}})

    def test_named_property_must_also_match_pattern_schema(self):
        schema={'type':'object','properties':{'x-id':{'type':'string'}},'patternProperties':{'^x-':{'minLength':3}},'additionalProperties':False}
        self.assertTrue(validate_tool_arguments(schema,{'x-id':'abc'}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'x-id':'a'})

    def test_pattern_schema_may_be_locally_referenced(self):
        schema={'type':'object','properties':{'copy':{'$ref':'#/patternProperties/%5Ex-'}},'patternProperties':{'^x-':{'type':'integer'}}}
        # Percent encoding remains unsupported; JSON Pointer escaping works for slash characters.
        with self.assertRaises(ValueError):validate_tool_arguments(schema,{'copy':1})
        schema={'type':'object','properties':{'copy':{'$ref':'#/patternProperties/~1'}},'patternProperties':{'/':{'type':'integer'}}}
        self.assertTrue(validate_tool_arguments(schema,{'copy':1,'a/b':2}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'copy':'bad'})

    def test_invalid_and_expensive_patterns_are_bounded(self):
        for pattern in ('[','a{1000000}'):
            with self.subTest(pattern=pattern),self.assertRaises(ValueError):validate_tool_arguments({'type':'object','patternProperties':{pattern:{}}},{})
        for schema in ({'type':'object','patternProperties':{'^(a+)+$':{}},'additionalProperties':False},{'type':'object','additionalProperties':False,'patternProperties':{'^(a+)+$':{}}}):
            with self.subTest(first=list(schema)[1]):
                start=time.monotonic()
                with self.assertRaises(ValueError):validate_tool_arguments(schema,{'a'*10000+'!':1})
                self.assertLess(time.monotonic()-start,2)


if __name__=='__main__':unittest.main()

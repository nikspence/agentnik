import unittest
from agentnik.mcp_schema import MCPArgumentValidationError,validate_tool_arguments,validate_tool_result


class UniqueItemsTests(unittest.TestCase):
    def schema(self,dialect=None):
        value={'type':'object','properties':{'items':{'type':'array','uniqueItems':True}},'required':['items']}
        if dialect:value['$schema']=dialect
        return value

    def test_json_schema_equality_for_nested_values(self):
        for dialect in (None,'http://json-schema.org/draft-07/schema#'):
            with self.subTest(dialect=dialect):
                schema=self.schema(dialect)
                self.assertTrue(validate_tool_arguments(schema,{'items':[True,1,False,0,None,'1',{'x':[True,1]},{'x':[1,True]}]}))
                for items in ([1,1.0],[{'a':1,'b':[True]},{'b':[True],'a':1.0}],[[{'x':1}],[{'x':1.0}]]):
                    with self.subTest(items=items),self.assertRaises(MCPArgumentValidationError) as caught:validate_tool_arguments(schema,{'items':items})
                    self.assertIn('duplicate items',str(caught.exception));self.assertNotIn(str(items),str(caught.exception))

    def test_false_and_invalid_keyword_values(self):
        schema=self.schema();schema['properties']['items']['uniqueItems']=False
        self.assertTrue(validate_tool_arguments(schema,{'items':[1,1]}))
        schema['properties']['items']['uniqueItems']='true'
        with self.assertRaises(ValueError):validate_tool_arguments(schema,{'items':[1]})

    def test_large_object_arrays_and_output_schema(self):
        schema=self.schema();items=[{'id':index,'tags':['x',index]} for index in range(1000)]
        self.assertTrue(validate_tool_arguments(schema,{'items':items}))
        tool={'output_schema_status':'available','output_schema':schema}
        with self.assertRaisesRegex(ValueError,'structured result'):validate_tool_result(tool,{'structuredContent':{'items':[{'id':1},{'id':1}]}})

    def test_unique_items_inside_local_schema_reference(self):
        schema={'type':'object','properties':{'items':{'$ref':'#/$defs/tagList'}},'$defs':{'tagList':{'type':'array','items':{'type':'string'},'uniqueItems':True}}}
        self.assertTrue(validate_tool_arguments(schema,{'items':['alpha','beta']}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'items':['alpha','alpha']})


if __name__=='__main__':unittest.main()

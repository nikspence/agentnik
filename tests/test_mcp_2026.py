import unittest

from agentnik.mcp_2026 import PROTOCOL,header_fields,header_value,prepare_request


class ModernMCPRequests(unittest.TestCase):
    def test_discovery_and_call_mirror_metadata_and_safe_values(self):
        message={'jsonrpc':'2.0','id':7,'method':'server/discover','params':{}}
        request,headers=prepare_request(message)
        self.assertEqual(headers,{'MCP-Protocol-Version':PROTOCOL,'Mcp-Method':'server/discover'})
        self.assertEqual(request['params']['_meta']['io.modelcontextprotocol/protocolVersion'],PROTOCOL)
        self.assertNotIn('_meta',message['params'])
        schema={'type':'object','properties':{'nested':{'type':'object','properties':{'region':{'type':'string','x-mcp-header':'Region'}}},'ok':{'type':'boolean','x-mcp-header':'Flag'}}}
        request,headers=prepare_request({'jsonrpc':'2.0','id':8,'method':'tools/call','params':{'name':'search 世界','arguments':{'nested':{'region':'eu'},'ok':False}}},schema)
        self.assertEqual(headers['Mcp-Name'],'=?base64?c2VhcmNoIOS4lueVjA==?=')
        self.assertEqual(headers['Mcp-Param-Region'],'eu');self.assertEqual(headers['Mcp-Param-Flag'],'false')
        self.assertEqual(request['params']['arguments']['nested']['region'],'eu')

    def test_encoding_and_invalid_header_annotations(self):
        self.assertEqual(header_value(' padded '),'=?base64?IHBhZGRlZCA=?=')
        self.assertEqual(header_value('line1\nline2'),'=?base64?bGluZTEKbGluZTI=?=')
        self.assertEqual(header_value('=?base64?literal?='),'=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=')
        with self.assertRaises(ValueError):header_value(2**53)
        for schema in (
            {'properties':{'a':{'type':'number','x-mcp-header':'A'}}},
            {'properties':{'a':{'type':'string','x-mcp-header':'A'},'b':{'type':'string','x-mcp-header':'a'}}},
            {'properties':{'a':{'type':'string','x-mcp-header':'Bad\r\nName'}}},
            {'properties':{'a':{'items':{'type':'string','x-mcp-header':'A'}}}},
            {'oneOf':[{'properties':{'a':{'type':'string','x-mcp-header':'A'}}}]},
        ):
            with self.subTest(schema=schema),self.assertRaises(ValueError):header_fields(schema)

    def test_missing_or_null_values_are_omitted_and_types_checked(self):
        schema={'properties':{'count':{'type':'integer','x-mcp-header':'Count'}}}
        message={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'counter','arguments':{'count':None}}}
        self.assertNotIn('Mcp-Param-Count',prepare_request(message,schema)[1])
        message['params']['arguments']['count']=True
        with self.assertRaises(ValueError):prepare_request(message,schema)

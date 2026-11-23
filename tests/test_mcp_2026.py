import unittest

from agentnik.mcp_2026 import PROTOCOL,header_fields,header_value,prepare_request,parse_discovery


class ModernMCPRequests(unittest.TestCase):
    def test_modern_discovery_preserves_bounded_server_guidance(self):
        from agentnik.mcp_support import MAX_SERVER_INSTRUCTIONS_BYTES
        result={'supportedVersions':[PROTOCOL],'capabilities':{},'instructions':'가'*4000}
        parsed=parse_discovery(result);self.assertTrue(parsed['instructions_clipped'])
        self.assertLessEqual(len(parsed['instructions'].encode('utf-8')),MAX_SERVER_INSTRUCTIONS_BYTES)
        for value in (None,False,[], '\ud800'):
            result['instructions']=value;self.assertNotIn('instructions',parse_discovery(result))
    def test_server_metadata_is_untrusted_optional_information(self):
        result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{}}}
        self.assertFalse(parse_discovery(result)['server_identity_reported'])
        result['_meta']={'io.modelcontextprotocol/serverInfo':{'name':'Example','version':'2'}}
        parsed=parse_discovery(result);self.assertTrue(parsed['server_identity_reported']);self.assertEqual((parsed['name'],parsed['version']),('Example','2'))
        result['_meta']['io.modelcontextprotocol/serverInfo']['name']='bad\nname'
        self.assertFalse(parse_discovery(result)['server_identity_reported'])

    def test_anonymous_servers_use_separate_connection_cache_scopes(self):
        from agentnik.mcp_code import CodingMCPBridge
        from types import SimpleNamespace
        server={'name':'Example','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        first=CodingMCPBridge(server,{'mcp_servers':[server]});second=CodingMCPBridge(server,{'mcp_servers':[server]})
        first.session=SimpleNamespace(token='');second.session=SimpleNamespace(token='')
        info={'name':'MCP server','version':'unknown','protocol':PROTOCOL,'server_identity_reported':False}
        first._discovered(info);second._discovered(info);self.assertNotEqual(first.cache_scope,second.cache_scope)
        info.update(name='Example',version='1',server_identity_reported=True)
        first._discovered(info);second._discovered(info);self.assertEqual(first.cache_scope,second.cache_scope)

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

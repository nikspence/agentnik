"""Shared validation of MCP resource and authorization metadata."""
from urllib.parse import urlsplit

from .mcp_oauth import _https_parts

MAX_METADATA=131072


def _same_resource(configured,claimed):
    configured=urlsplit(configured);claimed=urlsplit(claimed)
    if (configured.scheme.lower(),configured.hostname.lower(),configured.port or 443)!=(claimed.scheme.lower(),claimed.hostname.lower(),claimed.port or 443):return False
    resource_path=claimed.path.rstrip('/')
    return (not resource_path or configured.path==resource_path or configured.path.startswith(resource_path+'/')) and (not claimed.query or claimed.query==configured.query)


def parse_resource_metadata(document,resource_url):
    if not isinstance(document,dict):raise ValueError('Invalid protected resource metadata')
    _https_parts(resource_url,allow_query=True)
    resource=document.get('resource');_https_parts(resource,allow_query=True)
    if not _same_resource(resource_url,resource):raise ValueError('Protected resource metadata does not match the MCP server')
    issuers=document.get('authorization_servers')
    if not isinstance(issuers,list) or not 1<=len(issuers)<=20 or len(set(issuers))!=len(issuers):raise ValueError('Invalid authorization server list')
    for issuer in issuers:_https_parts(issuer)
    scopes=document.get('scopes_supported',[])
    if not isinstance(scopes,list) or len(scopes)>100 or any(not isinstance(s,str) or not s or len(s)>256 or any(ord(ch)<33 or ord(ch)>126 or ch in '"\\' for ch in s) for s in scopes):raise ValueError('Invalid OAuth scopes')
    return {'resource':resource,'issuers':issuers,'scopes_supported':scopes}


def parse_authorization_metadata(document,issuer):
    if not isinstance(document,dict) or document.get('issuer')!=issuer:raise ValueError('OAuth issuer does not match its metadata')
    authorization=document.get('authorization_endpoint');token=document.get('token_endpoint')
    _https_parts(authorization,allow_query=True);_https_parts(token,allow_query=True)
    methods=document.get('code_challenge_methods_supported',[])
    if not isinstance(methods,list) or any(not isinstance(value,str) for value in methods):raise ValueError('Invalid PKCE metadata')
    auth_methods=document.get('token_endpoint_auth_methods_supported')
    if auth_methods is not None and (not isinstance(auth_methods,list) or any(not isinstance(value,str) for value in auth_methods)):raise ValueError('Invalid OAuth client authentication metadata')
    grants=document.get('grant_types_supported',[])
    if not isinstance(grants,list) or any(not isinstance(value,str) for value in grants):raise ValueError('Invalid OAuth grant metadata')
    registration=document.get('registration_endpoint')
    if registration is not None:_https_parts(registration,allow_query=True)
    issuer_response=document.get('authorization_response_iss_parameter_supported',False)
    if type(issuer_response) is not bool:raise ValueError('Invalid OAuth issuer response metadata')
    metadata_documents=document.get('client_id_metadata_document_supported',False)
    if type(metadata_documents) is not bool:raise ValueError('Invalid OAuth client metadata document support')
    return {'issuer':issuer,'authorization_endpoint':authorization,'token_endpoint':token,'registration_endpoint':registration,'pkce_s256':'S256' in methods,'public_client_supported':auth_methods is None or 'none' in auth_methods,'refresh_grant_supported':'refresh_token' in grants,'authorization_response_iss_parameter_supported':issuer_response,'client_id_metadata_document_supported':metadata_documents}

"""MCP OAuth challenge and discovery URL handling; no network requests."""
import json
import re
from urllib.parse import parse_qsl,urlsplit,urlunsplit
from urllib.request import parse_http_list

_TOKEN=r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
_SCHEME=re.compile(r'^('+_TOKEN+r')\s+(.+)$')
_PARAM=re.compile(r'^('+_TOKEN+r')\s*=\s*("(?:[\x20-\x21\x23-\x5b\x5d-\x7e]|\\[\x20-\x7e])*"|'+_TOKEN+r')$')


def bearer_challenge(header):
    """Parse one unambiguous Bearer challenge, never trusting server text for display."""
    if not isinstance(header,str) or len(header)>8192 or any(ord(c)<32 or ord(c)>126 for c in header):return None
    current=None;found=[]
    for part in parse_http_list(header):
        part=part.strip();scheme=_SCHEME.fullmatch(part)
        if re.fullmatch(_TOKEN,part):
            current={} if part.lower()=='bearer' else None
            if current is not None:found.append(current)
            continue
        if scheme and not scheme.group(2).lstrip().startswith('='):
            current={} if scheme.group(1).lower()=='bearer' else None
            if current is not None:found.append(current)
            part=scheme.group(2).strip()
        if current is None:continue
        match=_PARAM.fullmatch(part)
        if not match:return None
        key=match.group(1).lower();value=match.group(2)
        if key in current:return None
        if value.startswith('"'):value=re.sub(r'\\(.)',r'\1',value[1:-1])
        current[key]=value
    return found[0] if len(found)==1 else None


def _https_parts(url,allow_query=False):
    if not isinstance(url,str) or not url or len(url)>2048 or any(c in '\\<>"`{}|^' or ord(c)<33 or ord(c)>126 for c in url):raise ValueError('Invalid OAuth URL')
    try:parts=urlsplit(url);port=parts.port
    except ValueError:raise ValueError('Invalid OAuth URL') from None
    if parts.scheme.lower()!='https' or not parts.hostname or parts.username is not None or parts.password is not None or parts.fragment or (parts.query and not allow_query):raise ValueError('OAuth URL must use HTTPS and omit credentials and fragments')
    return parts


def protected_resource_metadata_urls(resource_url,challenge=None):
    """Return challenge metadata URL or RFC 9728 well-known candidates in order."""
    resource=_https_parts(resource_url,allow_query=True)
    if challenge and 'resource_metadata' in challenge:
        metadata=challenge['resource_metadata'];_https_parts(metadata,allow_query=True);return [metadata]
    prefix=urlunsplit((resource.scheme,resource.netloc,'/.well-known/oauth-protected-resource','',''))
    path=resource.path if resource.path!='/' else ''
    return [prefix+path,prefix] if path else [prefix]


def authorization_server_metadata_urls(issuer_url):
    """Return RFC 8414 and OpenID discovery candidates in MCP priority order."""
    issuer=_https_parts(issuer_url);path=issuer.path if issuer.path!='/' else ''
    origin=urlunsplit((issuer.scheme,issuer.netloc,'','',''))
    urls=[origin+'/.well-known/oauth-authorization-server'+path,origin+'/.well-known/openid-configuration'+path]
    if path:urls.append(origin+path.rstrip('/')+'/.well-known/openid-configuration')
    return urls


def _object_pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate metadata field')
        result[key]=value
    return result


_RESERVED=frozenset(('client_id','response_type','redirect_uri','state','scope','resource','code_challenge','code_challenge_method','grant_type','code','code_verifier'))
_MAX_RESPONSE=65536


def parse_token_response(data,status,ctype):
    """Validate token material without exposing server-provided error text."""
    if status!=200 or ctype!='application/json':raise ValueError('Invalid token response')
    result=json.loads(bytes(data).decode('utf-8'),object_pairs_hook=_object_pairs)
    if not isinstance(result,dict) or not isinstance(result.get('token_type'),str) or result['token_type'].lower()!='bearer':raise ValueError('Invalid token response')
    token=result.get('access_token')
    if not isinstance(token,str) or not token or len(token)>4096 or any(not 33<=ord(ch)<=126 for ch in token):raise ValueError('Invalid token response')
    refresh=result.get('refresh_token')
    if refresh is not None and (not isinstance(refresh,str) or not refresh or len(refresh)>4096 or any(not 33<=ord(ch)<=126 for ch in refresh)):raise ValueError('Invalid token response')
    expiry=result.get('expires_in')
    if expiry is not None and (type(expiry) is not int or expiry<=0):raise ValueError('Invalid token response')
    return {'access_token':token,'refresh_token':refresh,'expires_in':expiry}


def _endpoint(url):
    parts=_https_parts(url,allow_query=True)
    if any(key.lower() in _RESERVED for key,_ in parse_qsl(parts.query,keep_blank_values=True,max_num_fields=100)):raise ValueError('Reserved OAuth endpoint query parameter')
    return parts

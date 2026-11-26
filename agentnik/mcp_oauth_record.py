"""Shared, UI-independent MCP OAuth keyring records."""
import json
import time

from .mcp_oauth import _https_parts,_endpoint,_object_pairs,parse_token_response

_FIELDS=frozenset(('version','resource_url','issuer','token_endpoint','client_id','access_token','refresh_token','expires_at','refresh_pending'))


def _visible(value,limit=4096):
    return isinstance(value,str) and bool(value) and len(value)<=limit and all(33<=ord(ch)<=126 for ch in value)


def validate_record(record,resource_url=None):
    if not isinstance(record,dict) or not _FIELDS.issubset(record) or set(record)-_FIELDS-{'client_id_expires_at'} or type(record['version']) is not int or record['version']!=1:raise ValueError('Invalid OAuth credential')
    _https_parts(record['resource_url'],allow_query=True);_https_parts(record['issuer']);_endpoint(record['token_endpoint'])
    if resource_url is not None and record['resource_url']!=resource_url:raise ValueError('OAuth credential does not match the server')
    if not _visible(record['client_id'],1024) or not _visible(record['access_token']):raise ValueError('Invalid OAuth credential')
    if record['refresh_token'] is not None and not _visible(record['refresh_token']):raise ValueError('Invalid OAuth credential')
    expiry=record['expires_at']
    if expiry is not None and (type(expiry) is not int or expiry<=0):raise ValueError('Invalid OAuth credential')
    if type(record['refresh_pending']) is not bool:raise ValueError('Invalid OAuth credential')
    client_expiry=record.get('client_id_expires_at')
    if client_expiry is not None and (type(client_expiry) is not int or client_expiry<=0):raise ValueError('Invalid OAuth credential')
    return dict(record)


def make_record(resource_url,issuer,token_endpoint,client_id,result,now=None,previous_refresh=None,client_id_expires_at=None):
    now=int(time.time()) if now is None else int(now)
    normalized=parse_token_response(json.dumps(dict(result,token_type='Bearer')).encode('utf-8'),200,'application/json')
    expires=normalized['expires_in']
    record={'version':1,'resource_url':resource_url,'issuer':issuer,'token_endpoint':token_endpoint,'client_id':client_id,'access_token':normalized['access_token'],'refresh_token':normalized['refresh_token'] or previous_refresh,'expires_at':now+expires if expires is not None else None,'refresh_pending':False}
    if client_id_expires_at is not None:record['client_id_expires_at']=client_id_expires_at
    return validate_record(record,resource_url)


def read_record(credential_id,resource_url,backend=None):
    if backend is None:import keyring as backend
    text=backend.get_password('Agentnik',credential_id)
    if not isinstance(text,str) or len(text)>20000:raise ValueError('OAuth credential unavailable')
    try:return validate_record(json.loads(text,object_pairs_hook=_object_pairs),resource_url)
    except (TypeError,ValueError,RecursionError):raise ValueError('OAuth credential unavailable or invalid') from None


def write_record(credential_id,record,backend=None):
    if backend is None:import keyring as backend
    record=validate_record(record)
    backend.set_password('Agentnik',credential_id,json.dumps(record,ensure_ascii=True,separators=(',',':')))


def credential_state(record,now=None):
    record=validate_record(record);now=int(time.time()) if now is None else int(now);expiry=record['expires_at']
    if record['refresh_pending']:return 'uncertain'
    if expiry is None:return 'ready'
    if record['refresh_token'] and expiry<=now+30:
        if record.get('client_id_expires_at') is not None and record['client_id_expires_at']<=now:return 'ready' if expiry>now else 'expired'
        return 'refresh'
    return 'ready' if expiry>now else 'expired'

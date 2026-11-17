"""Explicit, destination-scoped Git tokens in the OS credential store."""
import hashlib
from urllib.parse import urlsplit

SERVICE='Agentnik Git'


def credential_key(url,username):
    if not isinstance(url,str) or not isinstance(username,str) or not 1<=len(username)<=256 or ':' in username or any(not 33<=ord(ch)<=126 for ch in username):
        raise ValueError('Enter a valid Git username.')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or any(not 33<=ord(ch)<=126 for ch in url):
        raise ValueError('Invalid Git HTTPS destination.')
    try:parsed.port
    except ValueError:raise ValueError('Invalid Git HTTPS destination.') from None
    return hashlib.sha256((url+'\0'+username).encode('ascii')).hexdigest()


def save_token(url,username,token):
    if not isinstance(token,str) or not 1<=len(token)<=4096 or any(not 33<=ord(ch)<=126 for ch in token):raise ValueError('Enter a valid Git token.')
    import keyring
    keyring.set_password(SERVICE,credential_key(url,username),token)


def load_token(url,username):
    import keyring
    return keyring.get_password(SERVICE,credential_key(url,username))


def delete_token(url,username):
    import keyring
    keyring.delete_password(SERVICE,credential_key(url,username))

"""Review-bound edits of existing Agentnik tracks; no implicit writes."""
import copy
import hashlib
from .tracks import ROOT,MAX_DOCUMENT_BYTES,IDENTIFIER,parse_json,validate_track

NAMES=('spec.md','plan.md','track.json')


def digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()


def validate_edit(value):
    if not isinstance(value,dict) or set(value)!={'id','files','base'}:raise ValueError('Invalid track edit draft')
    ident=value['id'];content=value['files'];base=value['base']
    if not isinstance(ident,str) or not IDENTIFIER.fullmatch(ident):raise ValueError('Invalid track id')
    if not isinstance(content,dict) or set(content)!=set(NAMES) or not isinstance(base,dict) or set(base)!=set(NAMES):raise ValueError('Invalid track edit files')
    for name in NAMES:
        text=content[name];hash_value=base[name]
        if not isinstance(text,str) or '\x00' in text or len(text.encode('utf-8'))>MAX_DOCUMENT_BYTES:raise ValueError('Track files must be UTF-8 and at most 128,000 bytes')
        if not isinstance(hash_value,str) or len(hash_value)!=64 or any(c not in '0123456789abcdef' for c in hash_value):raise ValueError('Invalid original track snapshot')
    validate_track(parse_json(content['track.json']),ident)
    return copy.deepcopy(value)


def load_edit(files,ident):
    if not isinstance(ident,str) or not IDENTIFIER.fullmatch(ident):raise ValueError('Invalid track id')
    base=ROOT+'/'+ident+'/'
    content={name:files.read(base+name,remember=False,max_bytes=MAX_DOCUMENT_BYTES) for name in NAMES}
    return validate_edit({'id':ident,'files':content,'base':{name:digest(value) for name,value in content.items()}})


def apply_edit(files,draft,approve,on_change=lambda draft:None):
    """Review and apply each changed existing file; preserve partial progress."""
    draft=validate_edit(draft);root=ROOT+'/'+draft['id']+'/';applied=[]
    def check_bases():
        for name in NAMES:
            try:current=files.read(root+name,remember=False,max_bytes=MAX_DOCUMENT_BYTES)
            except (OSError,UnicodeError,ValueError):raise ValueError('A track file is unavailable or changed; inspect before continuing') from None
            if digest(current)!=draft['base'][name]:raise ValueError('A track file changed since review; inspect before continuing')
    check_bases()
    for name in NAMES:
        current=files.read(root+name,remember=True,max_bytes=MAX_DOCUMENT_BYTES)
        if digest(current)!=draft['base'][name]:raise ValueError('A track file changed since review; inspect before continuing')
        if current==draft['files'][name]:continue
        proposal=files.proposal(root+name,draft['files'][name])
        if proposal['base']!=draft['base'][name]:raise ValueError('A track file changed since review; inspect before continuing')
        if not approve(copy.deepcopy(proposal)):return {'status':'rejected','draft':draft,'last_path':root+name,'applied':applied}
        files.apply(proposal,check_bases);draft['base'][name]=digest(draft['files'][name]);applied.append(root+name);on_change(copy.deepcopy(draft))
    check_bases()
    return {'status':'completed','draft':draft,'applied':applied}

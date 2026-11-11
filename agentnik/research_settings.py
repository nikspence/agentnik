"""Validated research preferences and conservative capability invalidation."""
import json
from dataclasses import asdict
from . import core
from .tools import Capability, utc_now

FIELDS=('managed_tools','hosted_search')


def validate_research_config(config):
    from .routing import POLICIES, ACCESS_POLICIES
    for name in ('research_defaults','research_capabilities'):
        entries=config.get(name,{})
        if not isinstance(entries,dict): raise ValueError('Invalid research settings')
        for key,value in entries.items():
            parts=json.loads(key)
            if not isinstance(parts,list) or len(parts) not in (3,4) or not all(isinstance(v,str) for v in parts): raise ValueError('Invalid research scope')
            if name=='research_defaults':
                if len(parts)!=3: raise ValueError('Invalid defaults scope')
                _,url,protocol=parts
                if not isinstance(value,dict) or set(value)-{'policy','access_policy'}: raise ValueError('Invalid research defaults')
                if value.get('policy','Provider first') not in POLICIES or value.get('access_policy','public_fetch') not in ACCESS_POLICIES: raise ValueError('Invalid research defaults')
            else:
                url,protocol,_=parts[:3]
                if len(parts)==4 and (not parts[3] or len(parts[3])>128): raise ValueError('Invalid capability scope')
                if not isinstance(value,dict) or set(value)-set(FIELDS): raise ValueError('Invalid capability fields')
                for field,record in value.items():
                    if not isinstance(record,dict) or set(record)-{'state','at','evidence'}: raise ValueError('Invalid capability record')
                    cap=Capability(**record)
                    if not all(isinstance(v,str) for v in (cap.state,cap.at,cap.evidence)) or len(cap.at)>64 or len(cap.evidence)>4096: raise ValueError('Invalid capability evidence')
            core.base_url(url)
            if protocol not in core.PROTOCOLS: raise ValueError('Invalid research protocol')


def invalidate_capabilities(config, connections, reason='Connection settings or credentials changed; verification required'):
    scopes=set()
    for c in connections:
        try: scopes.add((core.base_url(c['url']),c.get('protocol','chat')))
        except (KeyError,ValueError,TypeError): continue
    from .subagent_capabilities import invalidate
    invalidate(config,scopes)
    for key,record in config.get('research_capabilities',{}).items():
        try: url,protocol,model=json.loads(key)[:3]
        except (ValueError,TypeError): continue
        if (url,protocol) not in scopes: continue
        for field in FIELDS:
            data=record.get(field,{})
            if data.get('state') in ('verified','unsupported'):
                # Keep explicit enablement, but never stale compatibility claims.
                state='configured' if data['state']=='verified' else 'unknown'
                record[field]=asdict(Capability(state,utc_now(),reason))

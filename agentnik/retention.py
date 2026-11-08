"""Bound new research metadata independently from model-context and wire limits."""
import json
import re


def retain_result(value, maximum):
    """Mutate only a detached snapshot; never alter live orchestration state."""
    state=value['research']
    def size(): return len(json.dumps(state).encode('utf-8'))
    if size()<=maximum: return value
    original=size()
    state['retention']={'truncated':True,'original_bytes':original,'limit_bytes':maximum}
    state['continuation_eligible']=False
    # Opaque continuation must be complete or omitted, never partially replayed.
    state['response_items']=[]; state['exchanges']=[]
    for source in state.get('sources',[]):
        if len(source.get('excerpt',''))>256:
            source['excerpt']=source['excerpt'][:256]; source['truncated']=True
    for key in ('events','tool_records','attempts','backend_attempts','provider_usage'):
        if isinstance(state.get(key),list): state[key]=state[key][-8:]
    notice={'kind':'limited','detail':'Saved research detail reached its size limit. Continuation is unavailable; start a new chat for further research.'}
    state.setdefault('events',[]).append(notice)
    if size()>maximum:
        # Retain a bounded summary when even provenance or provider metadata is large.
        route=state.get('route') if state.get('route') in ('hosted','managed') else 'managed'
        state.clear()
        state.update(version=2,route=route,status='limited',continuation_eligible=False,
                     retention={'truncated':True,'original_bytes':original,'limit_bytes':maximum},
                     sources=[],events=[notice],exchanges=[],response_items=[],
                     unverified_citations=sorted({ident for ident in re.findall(r'\[(S\d+)\]',value.get('text','')) if len(ident)<=32})[:16])
    return value

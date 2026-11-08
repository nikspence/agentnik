"""Safe inline citation formatting using recorded source IDs and provider spans."""
import re
from urllib.parse import quote
from .web import public_url


def cited_markdown(text,data):
    sources={s['id']:s for s in data.get('sources',[]) if isinstance(s,dict) and isinstance(s.get('id'),str)}
    def link(ident):
        try: url=public_url(sources[ident]['url'])
        except (ValueError,KeyError): return '['+ident+']'
        url=quote(url,safe=':/?&=%#+,;@!~$_-')
        return f'[**[{ident}]**](<{url}>)'
    annotations=data.get('annotations',[])
    if annotations:
        ranges={}
        for item in annotations:
            start,end=item.get('start_index'),item.get('end_index'); ident=item.get('source_id')
            if ident in sources and type(start) is int and type(end) is int and 0<=start<=end<=len(text):
                ranges.setdefault((start,end),[])
                if ident not in ranges[start,end]: ranges[start,end].append(ident)
        pieces=[]; cursor=0
        for (start,end),idents in sorted(ranges.items()):
            if start<cursor: continue
            pieces.extend([text[cursor:start],' '.join(link(i) for i in idents)]); cursor=end
        pieces.append(text[cursor:]); return ''.join(pieces)
    if data.get('route')=='hosted': return text
    return re.sub(r'\[(S\d+)\]',lambda m:link(m[1]) if m[1] in sources else m[0],text)

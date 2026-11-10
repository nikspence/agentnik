"""Direct-first page reads with bounded, disclosed service retrieval fallback."""
import json
import ssl
from .core import EndpointError
from .failures import classify
from .tools import AccessError,ResearchError,Source,utc_now
from .web import PublicWeb,PublicTransport,FilteredPageError,resolve_public,excerpt,filter_page

FETCH_KINDS=('firecrawl','firecrawl-keyless','exa','parallel','ollama')


def provider_page(spec,url,runtime,transport=None):
    kind=spec['kind'];key=spec.get('key','')
    if kind not in FETCH_KINDS:raise ResearchError('Provider has no page retrieval adapter')
    if kind!='firecrawl-keyless' and not key:raise ResearchError('Provider page retrieval requires its search credential')
    if kind=='firecrawl-keyless' and key:raise AccessError('Keyless retrieval must not receive a key')
    if key and (len(key)>4096 or any(not 33<=ord(ch)<=126 for ch in key)):raise ResearchError('Invalid provider credential')
    url,_=resolve_public(url,runtime)
    if key and key in url:raise AccessError('Credential transmission blocked')
    headers={'Content-Type':'application/json','Accept':'application/json'}
    if kind in ('firecrawl','firecrawl-keyless'):
        endpoint='https://api.firecrawl.dev/v2/scrape';body={'url':url,'formats':['markdown'],'onlyMainContent':True}
    elif kind=='exa':endpoint='https://api.exa.ai/contents';body={'urls':[url],'text':True}
    elif kind=='parallel':endpoint='https://api.parallel.ai/v1/extract';body={'urls':[url],'max_chars_total':8000}
    else:endpoint='https://ollama.com/api/web_fetch';body={'url':url}
    if key:headers['x-api-key' if kind in ('exa','parallel') else 'Authorization']=key if kind in ('exa','parallel') else 'Bearer '+key
    runtime.check()
    _,_,raw=(transport or PublicTransport()).request(endpoint,runtime,body=json.dumps(body).encode(),headers=headers,redirects=False)
    runtime.check()
    try:
        data=json.loads(raw);final=url;title=url
        if not isinstance(data,dict):raise ValueError()
        if kind in ('firecrawl','firecrawl-keyless'):
            if data.get('success') is not True:raise ValueError()
            page=data['data'];text=page['markdown'];metadata=page.get('metadata',{})
            if not isinstance(metadata,dict):raise ValueError()
            status=metadata.get('statusCode',200)
            if status in (401,403,451):raise AccessError('Provider reported access-restricted page')
            if type(status) is not int or status>=400:raise ValueError()
            final=metadata.get('url') or metadata.get('sourceURL') or url;title=metadata.get('title') or final
        elif kind in ('exa','parallel'):
            pages=data['results']
            if not isinstance(pages,list) or len(pages)!=1 or not isinstance(pages[0],dict):raise ValueError()
            page=pages[0];final=page['url'];title=page.get('title') or final
            if kind=='exa':text=page['text']
            else:
                parts=page['excerpts']
                if not isinstance(parts,list) or any(not isinstance(part,str) for part in parts):raise ValueError()
                text='\n'.join(parts)
        else:text=data['content'];title=data.get('title') or url
        if not isinstance(text,str) or not text.strip() or not isinstance(title,str) or not isinstance(final,str):raise ValueError()
    except AccessError:raise
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError):raise ResearchError('Malformed or empty provider page response') from None
    final,_=resolve_public(final,runtime)
    if key and key in text+title+final:raise AccessError('Provider page contains a configured credential')
    if filter_page(text.encode()):raise AccessError('Provider returned a web-filter block page')
    text,truncated=excerpt(text,8000)
    return [Source('',title[:300],final,text,utc_now(),'text/plain',truncated,spec['id']+'-page-api')]


class PageFetcher:
    def __init__(self,specs,direct=None,allow_external=True):
        self.direct=direct or PublicWeb();self.allow_external=allow_external
        self.specs=[dict(spec) for spec in specs if spec.get('kind') in FETCH_KINDS]
        if not any(spec['kind']=='firecrawl-keyless' for spec in self.specs):
            self.specs.append({'id':'builtin-firecrawl-keyless','kind':'firecrawl-keyless','name':'Firecrawl Keyless','key':''})

    def fetch(self,url,runtime):
        try:return self.direct.fetch(url,runtime)
        except (FilteredPageError,ssl.SSLError,ConnectionResetError):
            if not self.allow_external:raise
            runtime.check();url,_=resolve_public(url,runtime)
        seen=set();last=None
        for spec in self.specs:
            runtime.check();kind=spec['kind'];key=spec.get('key','')
            if kind!='firecrawl-keyless' and not key:continue
            identity=(kind,key)
            if identity in seen:continue
            seen.add(identity)
            notify=getattr(runtime,'notify',None)
            if notify:notify('fetch_fallback','Direct fetch was filtered or its TLS/connection failed; sending the public page URL to '+spec.get('name',kind)+' for provider retrieval. Provider navigation is external and charges may apply.')
            try:return provider_page(spec,url,runtime)
            except Exception as exc:
                last=exc;failure=classify(exc,False)
                if not failure['fallback_allowed']:raise
                if notify:notify('fetch_provider_failed',spec.get('name',kind)+': '+failure['kind'])
        if last:raise last
        raise ResearchError('No eligible provider page retrieval service')

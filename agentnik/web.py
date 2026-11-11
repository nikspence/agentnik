"""Public-only page transport and replaceable managed search adapter.

Search contracts and implemented scope: see SEARCH_PROVIDERS.md.
Direct fetch is primary; filtered connections can use disclosed provider retrieval fallback.
"""
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, urlencode, parse_qs
from .tools import AccessError, LimitError, ResearchError, Source, utc_now
from .core import EndpointError
from . import __version__
from .search_providers import search_ready,search_chain


class FilteredPageError(ResearchError):
    """A recognizable network web-filter response, distinct from URL-policy rejection."""


def filter_page(payload,server=''):
    vendor=r'zscaler|netskope|forcepoint|websense|blue coat'
    if isinstance(server,str) and re.search(vendor,server,re.I):return True
    if not isinstance(payload,bytes):return False
    text=payload[:16384].decode('utf-8','replace').lower()
    title=re.search(r'<title[^>]*>(.*?)</title>',text,re.S)
    title=title.group(1) if title else (text.splitlines()[0].lstrip('# ').strip() if text.startswith('#') else '')
    blocked=r'access denied|access blocked|url blocked|web site blocked|website blocked|request blocked|web access denied'
    return bool(re.search(vendor,text) and (re.search(blocked,title) or (re.search(vendor,title) and (re.search(r'internet security|web security|security notification',title) or title.strip() in ('zscaler','netskope','forcepoint','websense','blue coat')) and re.search(blocked,text))))


def public_url(url):
    if not isinstance(url,str) or len(url)>2048 or re.search(r'[\x00-\x20\x7f\\]',url):
        raise AccessError('Invalid public URL')
    try:
        p=urlsplit(url); port=p.port
        host=p.hostname
        if p.scheme not in ('http','https') or not host or p.username is not None or p.password is not None:
            raise ValueError()
        if port not in (None,80,443): raise ValueError()
        host=host.rstrip('.').encode('idna').decode('ascii').lower()
        if host=='localhost' or host.endswith(('.localhost','.local','.internal','.home','.test','.invalid')) or '%' in host:
            raise ValueError()
        try:
            address=ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host: raise ValueError()
        else:
            if not address.is_global or address.is_multicast or getattr(address,'ipv4_mapped',None) or getattr(address,'sixtofour',None) or getattr(address,'teredo',None):
                raise ValueError()
        authority=f'[{host}]' if ':' in host else host
        if port: authority+=':'+str(port)
        return urlunsplit((p.scheme,authority,p.path or '/',p.query,''))
    except (ValueError,UnicodeError): raise AccessError('Only public HTTP(S) destinations on ports 80/443 are allowed') from None


def resolve_public(url,runtime):
    url=public_url(url); p=urlsplit(url)
    addresses=runtime.wait(lambda:socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM))
    if not addresses: raise AccessError('Destination has no public address')
    for family,kind,proto,canon,address in addresses:
        ip=ipaddress.ip_address(address[0])
        if not ip.is_global or ip.is_multicast or getattr(ip,'ipv4_mapped',None) or getattr(ip,'sixtofour',None) or getattr(ip,'teredo',None):
            raise AccessError('Destination resolves to a restricted address')
    return url,addresses


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self,url,addresses,timeout,verify_tls=True):
        self.destination=urlsplit(url); self.addresses=addresses;self.verify_tls=verify_tls
        super().__init__(self.destination.hostname,self.destination.port or (443 if self.destination.scheme=='https' else 80),timeout=timeout)

    def connect(self):
        # Retry only TCP connection establishment, before any HTTP submission.
        # TLS failures are terminal; no second DNS lookup or request replay.
        deadline=time.monotonic()+self.timeout
        seen=set(); last_error=None
        for family,kind,proto,canon,address in self.addresses:
            identity=(family,kind,proto,address)
            if identity in seen: continue
            if len(seen)>=8: break
            seen.add(identity)
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError('Public connection deadline reached')
            sock=socket.socket(family,kind,proto); sock.settimeout(remaining)
            try: sock.connect(address)
            except OSError as exc:
                sock.close(); last_error=exc; continue
            try:
                remaining=deadline-time.monotonic()
                if remaining<=0: raise TimeoutError('Public connection deadline reached')
                sock.settimeout(remaining)
                if self.destination.scheme=='https':
                    context=ssl.create_default_context()
                    if not self.verify_tls:
                        context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
                    sock=context.wrap_socket(sock,server_hostname=self.destination.hostname)
                self.sock=sock; return
            except Exception:
                sock.close(); raise
        if last_error is not None: raise last_error
        raise OSError('No approved public address available')



def read_bounded(response,connection,runtime):
    encoding=response.getheader('Content-Encoding','identity').lower()
    if encoding not in ('','identity'): raise AccessError('Compressed page responses are not accepted')
    length=response.getheader('Content-Length')
    if length:
        try: size=int(length)
        except ValueError: raise ResearchError('Invalid response length') from None
        if size<0 or size>runtime.limits.response_bytes: raise LimitError('Page response byte limit reached')
    data=bytearray(); deadline=time.monotonic()+runtime.timeout()
    while True:
        runtime.check()
        left=deadline-time.monotonic()
        if left<=0: raise LimitError('Page request time limit reached')
        if connection.sock: connection.sock.settimeout(min(left,runtime.timeout()))
        chunk=response.read1(min(16384,runtime.limits.response_bytes+1-len(data)))
        runtime.check()
        if not chunk: break
        runtime.charge('retrieved_bytes',len(chunk),runtime.limits.retrieved_bytes)
        data.extend(chunk)
        if len(data)>runtime.limits.response_bytes: raise LimitError('Page response byte limit reached')
    return bytes(data)


class PublicTransport:
    """No proxies, cookies, provider credentials, automatic redirects, or compression."""
    def __init__(self,verify_tls=True):self.verify_tls=verify_tls
    def request(self,url,runtime,body=None,headers=None,redirects=True):
        for hop in range(runtime.limits.redirects+1):
            url,addresses=resolve_public(url,runtime)
            c=PinnedConnection(url,addresses,runtime.timeout(),verify_tls=self.verify_tls)
            p=urlsplit(url); path=p.path+('?' +p.query if p.query else '')
            request_headers={'Accept-Encoding':'identity','User-Agent':'Agentnik/'+__version__}
            request_headers.update(headers or {})
            try:
                c.request('POST' if body is not None else 'GET',path,body=body,headers=request_headers)
                r=c.getresponse(); runtime.check()
                if r.status in (301,302,303,307,308):
                    if not redirects: raise AccessError('Search service redirects are blocked')
                    if hop>=runtime.limits.redirects: raise LimitError('Page redirect limit reached')
                    location=r.getheader('Location')
                    if not location: raise ResearchError('Redirect without destination')
                    url=public_url(urljoin(url,location))
                    continue
                if r.status!=200:
                    if body is None and redirects and r.status in (403,451):
                        server=r.getheader('Server','')
                        if filter_page(b'',server):raise FilteredPageError('Direct page request blocked by a network web filter')
                        sample=r.read(4096)
                        if isinstance(sample,bytes):runtime.charge('retrieved_bytes',len(sample),runtime.limits.retrieved_bytes)
                        if filter_page(sample):raise FilteredPageError('Direct page request blocked by a network web filter')
                    # Avoid echoing upstream error bodies, query strings, or credentials.
                    raise EndpointError(r.status,json.dumps({'error':{'message':'Web service rejected the request'}}),r.getheader('Retry-After'))
                ctype=r.getheader('Content-Type','').split(';')[0].strip().lower()
                brave_json=(urlsplit(url).scheme=='https' and urlsplit(url).netloc=='api.search.brave.com' and urlsplit(url).path=='/res/v1/web/search' and not redirects)
                allowed=('application/json',) if body is not None or brave_json else ('text/html','text/plain','application/xhtml+xml')
                # Ollama's search API can label its JSON payload as text/html.
                # Permit that label only for this fixed POST endpoint; OllamaWeb
                # still requires valid JSON and the expected results schema.
                mislabeled_search = (body is not None and url=='https://ollama.com/api/web_search'
                                     and not redirects and ctype=='text/html')
                if ctype not in allowed and not mislabeled_search: raise AccessError('Unsupported web content type')
                payload=read_bounded(r,c,runtime)
                return url,ctype,payload
            finally: c.close()
        raise LimitError('Page redirect limit reached')


class ReadableText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.hidden=0; self.parts=[]; self.title=[]; self.in_title=False

    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','template','svg'): self.hidden+=1
        if tag=='title': self.in_title=True
        if tag in ('p','div','br','li','h1','h2','h3','section','article'): self.parts.append('\n')

    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','template','svg') and self.hidden: self.hidden-=1
        if tag=='title': self.in_title=False

    def handle_data(self,data):
        if not self.hidden:
            if self.in_title: self.title.append(data)
            else: self.parts.append(data)


class PageLinks(HTMLParser):
    """Collect a bounded set of same-host documentation links, without fetching them."""
    def __init__(self,base):
        super().__init__(convert_charrefs=True);self.base=base;self.host=urlsplit(base).hostname;self.links=[];self.seen=set();self.current=None
    def handle_starttag(self,tag,attrs):
        if tag!='a' or len(self.links)>=64:return
        href=dict(attrs).get('href','')
        try:
            url=public_url(urljoin(self.base,href))
            if not href or urlsplit(url).hostname!=self.host or url==self.base or url in self.seen:return
        except (TypeError,ValueError):return
        self.current=[url,[]]
    def handle_data(self,data):
        if self.current is not None:self.current[1].append(data[:300])
    def handle_endtag(self,tag):
        if tag=='a' and self.current:
            url,parts=self.current;self.current=None
            title=' '.join(''.join(parts).split())[:200]
            if title and url not in self.seen:self.seen.add(url);self.links.append((title,url))


class GoogleResults(HTMLParser):
    """Extract result links with headings from Google's public HTML response."""
    def __init__(self):
        super().__init__(convert_charrefs=True);self.anchor=None;self.heading=False;self.results=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.anchor=[dict(attrs).get('href',''),[]]
        elif tag=='h3' and self.anchor is not None:self.heading=True
    def handle_data(self,data):
        if self.heading and self.anchor is not None:self.anchor[1].append(data[:300])
    def handle_endtag(self,tag):
        if tag=='h3':self.heading=False
        elif tag=='a' and self.anchor is not None:
            href,parts=self.anchor;self.anchor=None;title=' '.join(''.join(parts).split())[:200]
            if title:self.results.append((title,href))


def excerpt(text,size):
    raw=text.encode('utf-8'); clipped=raw[:size].decode('utf-8','ignore')
    return clipped,len(raw)>size


class PublicWeb:
    """Read public pages without any search credential."""
    def __init__(self,transport=None,include_links=False):self.transport=transport or PublicTransport(verify_tls=False);self.include_links=include_links
    def fetch(self,url,runtime):
        final,ctype,payload=self.transport.request(url,runtime)
        if filter_page(payload):raise FilteredPageError('Direct page response is a network web-filter block page')
        text=payload.decode('utf-8','replace');title=final;links=[]
        if ctype in ('text/html','application/xhtml+xml'):
            parser=ReadableText();parser.feed(text)
            if self.include_links:
                link_parser=PageLinks(final);link_parser.feed(text);links=link_parser.links
            text=''.join(parser.parts);title=''.join(parser.title).strip() or final
        text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]','',text)
        text=re.sub(r'[ \t]+',' ',text);text=re.sub(r'\n\s*\n','\n\n',text).strip()
        text,truncated=excerpt(text,8000)
        result=[Source('',title[:300],final,text,utc_now(),ctype,truncated,'public-fetch')]
        for link_title,link in links[:max(0,runtime.limits.results-1)]:
            result.append(Source('',link_title,link,'Link found on the fetched page; not yet fetched.',utc_now(),backend='public-link'))
        return result


class GoogleWeb(PublicWeb):
    """Search the public Google HTML page without cookies or challenge bypass."""
    def __init__(self,transport=None,include_links=False):super().__init__(transport or PublicTransport(),include_links)
    def search(self,query,runtime):
        url='https://www.google.com/search?'+urlencode({'q':query})
        try:_,ctype,payload=self.transport.request(url,runtime,redirects=False)
        except AccessError:
            raise ResearchError('Google Search blocked the request or requires a browser challenge') from None
        except EndpointError as exc:
            if exc.status in (403,429):raise ResearchError('Google Search blocked the request or requires a browser challenge') from None
            raise
        if ctype not in ('text/html','application/xhtml+xml'):raise ResearchError('Google Search returned an unsupported response')
        parser=GoogleResults();parser.feed(payload.decode('utf-8','replace'));results=[];seen=set()
        for title,href in parser.results:
            runtime.check()
            try:
                parsed=urlsplit(href)
                if parsed.path=='/url' and (not parsed.hostname or parsed.hostname in ('google.com','www.google.com')):
                    href=parse_qs(parsed.query).get('q',[''])[0]
                target=public_url(href);host=urlsplit(target).hostname
                if host=='google.com' or host.endswith('.google.com') or target in seen:continue
                target,_=resolve_public(target,runtime)
            except (LimitError,InterruptedError):raise
            except (ValueError,OSError):continue
            seen.add(target);results.append(Source('',title,target,'Google search result; fetch the page to inspect it.',utc_now(),backend='google-search'))
            if len(results)>=runtime.limits.results:break
        if not results:raise ResearchError('Google Search returned no recognizable results or requires a browser challenge')
        return results


class OllamaWeb(PublicWeb):
    """Queries only are sent to Ollama search. Page reads use PublicTransport."""
    def __init__(self,key,transport=None):
        if not isinstance(key,str) or not key.strip(): raise ResearchError('Configure a separate Ollama web-search key first')
        if len(key)>4096 or any(not 33<=ord(ch)<=126 for ch in key):
            raise ResearchError('Search credential must be a single visible ASCII token')
        super().__init__(transport or PublicTransport());self.key=key

    def search(self,query,runtime):
        body=json.dumps({'query':query,'max_results':min(runtime.limits.results,10)}).encode()
        _,_,payload=self.transport.request('https://ollama.com/api/web_search',runtime,body=body,
                  headers={'Content-Type':'application/json','Authorization':'Bearer '+self.key},redirects=False)
        try: data=json.loads(payload)
        except (ValueError,RecursionError): raise ResearchError('Malformed search response') from None
        if not isinstance(data,dict) or not isinstance(data.get('results'),list): raise ResearchError('Malformed search results')
        result=[]
        for item in data['results'][:runtime.limits.results]:
            runtime.check()
            if not isinstance(item,dict) or not all(isinstance(item.get(k),str) for k in ('title','url','content')):
                raise ResearchError('Malformed search result')
            # Do not turn private search-result URLs into links or fetch targets.
            url,_=resolve_public(item['url'],runtime)
            text,truncated=excerpt(item['content'],3000)
            result.append(Source('',item['title'][:300],url,text,utc_now(),truncated=truncated,backend='ollama-search'))
        return result

class KeyedSearch(PublicWeb):
    """Independent search credential, shared only with a fixed provider endpoint."""
    provider_label='search provider'

    def __init__(self,key,transport=None):
        if not isinstance(key,str) or not key.strip():raise ResearchError('Configure a '+self.provider_label+' API key first')
        if len(key)>4096 or any(not 33<=ord(ch)<=126 for ch in key):raise ResearchError('Search credential must be a single visible ASCII token')
        super().__init__(transport or PublicTransport());self.key=key


class BraveWeb(KeyedSearch):
    """Brave Web Search: query-only disclosure, fixed service and separate key."""
    provider_label='Brave Search'

    def search(self,query,runtime):
        if not isinstance(query,str) or not query.strip() or len(query)>600 or len(query.split())>75:
            raise ResearchError('Brave search requires at most 600 characters and 75 words')
        if self.key in query:raise AccessError('Search credential transmission blocked')
        url='https://api.search.brave.com/res/v1/web/search?'+urlencode({'q':query,'count':min(runtime.limits.results,20),'text_decorations':'false','result_filter':'web'})
        _,_,payload=self.transport.request(url,runtime,headers={'Accept':'application/json','X-Subscription-Token':self.key},redirects=False)
        try:data=json.loads(payload)
        except (ValueError,RecursionError):raise ResearchError('Malformed Brave search response') from None
        if not isinstance(data,dict) or data.get('type')=='ErrorResponse':raise ResearchError('Malformed Brave search response')
        section=data.get('web')
        if section is None:
            if isinstance(data.get('query'),dict):return []
            raise ResearchError('Malformed Brave search results')
        if not isinstance(section,dict) or not isinstance(section.get('results'),list):raise ResearchError('Malformed Brave search results')
        results=[]
        for item in section['results'][:runtime.limits.results]:
            runtime.check()
            if not isinstance(item,dict) or not all(isinstance(item.get(k),str) for k in ('title','url')) or (item.get('description') is not None and not isinstance(item['description'],str)):raise ResearchError('Malformed Brave search result')
            # Reject rather than publish private or credential-bearing destinations.
            if self.key in json.dumps(item):raise AccessError('Search response contains a configured credential')
            try:target,_=resolve_public(item['url'],runtime)
            except AccessError:
                callback=getattr(runtime,'notify',None)
                if callback:callback('result_filtered','Brave Search: a non-public or invalid result was omitted.')
                continue
            parser=ReadableText();parser.feed(item.get('description') or '')
            text,truncated=excerpt(re.sub(r'\s+',' ',''.join(parser.parts)).strip(),3000)
            results.append(Source('',item['title'][:300],target,text,utc_now(),truncated=truncated,backend='brave-search'))
        return results


class SnippetSearch(KeyedSearch):
    """Fixed-endpoint JSON search; no crawl, scrape, or full-text expansion."""
    def search(self,query,runtime):
        if not isinstance(query,str) or not query.strip() or len(query)>500:raise ResearchError('Search query must contain 1–500 characters')
        if self.key and self.key in query:raise AccessError('Search credential transmission blocked')
        if self.provider_label=='LangSearch':
            url='https://api.langsearch.com/v1/web-search'
            body={'query':query,'count':min(runtime.limits.results,50),'contents':{'text':False}}
        else:
            url='https://api.firecrawl.dev/v2/search'
            body={'query':query,'limit':min(runtime.limits.results,100),'sources':[{'type':'web'}]}
        runtime.check();headers={'Content-Type':'application/json','Accept':'application/json'}
        if self.key:headers['Authorization']='Bearer '+self.key
        _,_,payload=self.transport.request(url,runtime,body=json.dumps(body).encode(),headers=headers,redirects=False)
        runtime.check()
        try:
            data=json.loads(payload)
            if self.provider_label=='LangSearch':
                if type(data.get('code')) is not int or data['code']!=200:raise ValueError()
                items=data['data']['webPages']['value'];title_key='name';description_key='snippet'
            else:
                if data.get('success') is not True:raise ValueError()
                items=data['data']['web'];title_key='title';description_key='description'
            if not isinstance(items,list):raise ValueError()
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError):raise ResearchError('Malformed '+self.provider_label+' search response') from None
        results=[]
        for item in items[:runtime.limits.results]:
            runtime.check()
            if not isinstance(item,dict) or not all(isinstance(item.get(k),str) for k in (title_key,'url')) or (item.get(description_key) is not None and not isinstance(item[description_key],str)):raise ResearchError('Malformed search result')
            if self.key and self.key in json.dumps(item):raise AccessError('Search response contains a configured credential')
            target,_=resolve_public(item['url'],runtime)
            parser=ReadableText();parser.feed(item.get(description_key) or '')
            text,truncated=excerpt(re.sub(r'\s+',' ',''.join(parser.parts)).strip(),3000)
            results.append(Source('',item[title_key][:300],target,text,utc_now(),truncated=truncated,backend=self.provider_label.lower()+'-search'))
        return results


class LangSearchWeb(SnippetSearch):
    provider_label='LangSearch'


class FirecrawlWeb(SnippetSearch):
    provider_label='Firecrawl'



class FirecrawlKeylessWeb(FirecrawlWeb):
    """Explicit keyless REST access; never consume an account or environment key."""
    def __init__(self,key='',transport=None):
        if key:raise ResearchError('Keyless Firecrawl must not receive an API key')
        PublicWeb.__init__(self,transport or PublicTransport());self.key=''


class ExcerptSearch(KeyedSearch):
    """Search plus provider excerpts, with no autonomous tasks or full-text mode."""
    def search(self,query,runtime):
        if not isinstance(query,str) or not query.strip() or len(query)>1000:raise ResearchError('Search query must contain 1–1000 characters')
        if self.key in query:raise AccessError('Search credential transmission blocked')
        runtime.check();body=self.request_body(query,runtime)
        _,_,payload=self.transport.request(self.service_url,runtime,body=json.dumps(body).encode(),
                    headers={'Content-Type':'application/json','Accept':'application/json','x-api-key':self.key},redirects=False)
        runtime.check()
        try:data=json.loads(payload)
        except (ValueError,RecursionError):raise ResearchError('Malformed '+self.provider_label+' search response') from None
        if not isinstance(data,dict) or 'error' in data or data.get('type')=='error' or not isinstance(data.get('results'),list):
            raise ResearchError('Malformed '+self.provider_label+' search results')
        results=[]
        for item in data['results'][:runtime.limits.results]:
            runtime.check()
            if not isinstance(item,dict) or not all(isinstance(item.get(key),str) for key in ('title','url')):raise ResearchError('Malformed search result')
            parts=item.get(self.excerpt_field,[])
            if not isinstance(parts,list) or any(not isinstance(part,str) for part in parts):raise ResearchError('Malformed search excerpts')
            if self.key in json.dumps(item):raise AccessError('Search response contains a configured credential')
            target,_=resolve_public(item['url'],runtime)
            text,truncated=excerpt('\n'.join(parts),3000)
            results.append(Source('',item['title'][:300],target,text,utc_now(),truncated=truncated,backend=self.backend_name))
        return results


class ExaWeb(ExcerptSearch):
    provider_label='Exa'
    service_url='https://api.exa.ai/search'
    excerpt_field='highlights'
    backend_name='exa-search'

    def request_body(self,query,runtime):
        return {'query':query,'type':'auto','numResults':min(runtime.limits.results,100),'contents':{'highlights':True}}


class ParallelWeb(ExcerptSearch):
    provider_label='Parallel'
    service_url='https://api.parallel.ai/v1/search'
    excerpt_field='excerpts'
    backend_name='parallel-search'

    def request_body(self,query,runtime):
        return {'search_queries':[query],'mode':'basic','max_chars_total':min(runtime.limits.context_bytes,runtime.limits.results*3000)}


class OrderedSearch:
    """Resolve one logical search call across an explicit ordered backend list."""
    def __init__(self,specs,allow_fallback=True):
        if len(specs)>5:raise ResearchError('At most five configured search profiles are supported')
        self.specs=search_chain(specs) if allow_fallback else specs; self.allow_fallback=allow_fallback; self.attempts=[];self.unavailable=set()
        self.secret_values=[s.get('key','') for s in specs]

    def notify(self,runtime,kind,detail):
        callback=getattr(runtime,'notify',None)
        if callback: callback(kind,detail)

    def search(self,query,runtime):
        from dataclasses import replace
        from .failures import classify
        last=None; seen_ids=set(); seen_credentials=set()
        for spec in self.specs:
            runtime.check()
            ident=spec.get('id',''); name=spec.get('name',ident)
            record={'backend':ident,'name':name,'status':'running','started_at':utc_now()}
            self.attempts.append(record)
            keyless=spec.get('kind') in ('firecrawl-keyless','google')
            credential=(spec.get('kind'),'' if keyless else spec.get('key'))
            if ident in self.unavailable:
                record.update(status='skipped',reason='Backend unavailable for this run after rejection',ended_at=utc_now())
                self.notify(runtime,'backend_skipped',name+': '+record['reason']);continue
            if ident in seen_ids or ((spec.get('key') or keyless) and credential in seen_credentials):
                record.update(status='skipped',reason='Duplicate backend/profile credential',ended_at=utc_now())
                self.notify(runtime,'backend_skipped',name+': duplicate profile'); continue
            seen_ids.add(ident)
            if spec.get('key') or keyless: seen_credentials.add(credential)
            if not search_ready(spec):
                record.update(status='skipped',reason='Unsupported backend or missing credential',ended_at=utc_now())
                self.notify(runtime,'backend_skipped',name+': '+record['reason']); continue
            self.notify(runtime,'backend_selected',name)
            try:
                adapter={'google':GoogleWeb,'brave':BraveWeb,'langsearch':LangSearchWeb,'firecrawl':FirecrawlWeb,'firecrawl-keyless':FirecrawlKeylessWeb,'exa':ExaWeb,'parallel':ParallelWeb,'ollama':OllamaWeb}[spec['kind']]
                service=adapter() if spec['kind']=='google' else adapter(spec.get('key',''))
                result=service.search(query,runtime)
                record.update(status='completed',ended_at=utc_now())
                # An empty result is evidence, not a reason to try another backend.
                return [replace(source,backend=ident) for source in result]
            except Exception as exc:
                failure=classify(exc,False); last=exc
                record.update(status='failed',error=str(exc)[:500],failure=failure,ended_at=utc_now())
                detail=name+': '+failure['kind']
                if failure['http_status'] is not None:detail+=' (HTTP '+str(failure['http_status'])+')'
                elif isinstance(exc,AccessError):
                    known={'Search credential transmission blocked':'credential in query blocked','Search response contains a configured credential':'credential reflected in response','Only public HTTP(S) destinations on ports 80/443 are allowed':'destination rejected by public URL policy','Invalid public URL':'invalid public URL','Destination has no public address':'destination has no public address','Destination resolves to a restricted address':'destination resolves to a restricted address','Search service redirects are blocked':'provider redirect blocked','Unsupported web content type':'unsupported response content type','Compressed page responses are not accepted':'unsupported response encoding'}
                    if str(exc) in known:detail+=' ('+known[str(exc)]+')'
                self.notify(runtime,'backend_failed',detail)
                if not self.allow_fallback or not failure['fallback_allowed']: raise
                if failure['kind'] in ('rate_limit','authentication'):self.unavailable.add(ident)
                if failure['kind'] in ('rate_limit','temporary'):
                    delay=failure['retry_after'] or 0
                    self.notify(runtime,'backend_wait',f'{delay:g}s retry guidance from '+name)
                    if delay<=runtime.limits.backoff_seconds:runtime.pause(delay)
                    else:self.notify(runtime,'backend_wait',name+': not retried; guidance exceeds wait budget, considering a different service')
                self.notify(runtime,'backend_switch','Considering the next configured search backend')
        if last: raise last
        raise ResearchError('No eligible managed search backend')

    def fetch(self,url,runtime):
        from .page_fetch import PageFetcher
        return PageFetcher(self.specs).fetch(url,runtime)

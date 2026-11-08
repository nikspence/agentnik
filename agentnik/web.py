"""Public-only page transport and replaceable managed search adapter.

Ollama contract: https://docs.ollama.com/capabilities/web-search
Service-backed fetch is intentionally not used: its redirects cannot be pinned here.
"""
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from .tools import AccessError, LimitError, ResearchError, Source, utc_now


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
    def __init__(self,url,addresses,timeout):
        self.destination=urlsplit(url); self.addresses=addresses
        super().__init__(self.destination.hostname,self.destination.port or (443 if self.destination.scheme=='https' else 80),timeout=timeout)

    def connect(self):
        # Connect only to a vetted address; never resolve the hostname a second time.
        family,kind,proto,canon,address=self.addresses[0]
        sock=socket.socket(family,kind,proto); sock.settimeout(self.timeout)
        try:
            sock.connect(address)
            if self.destination.scheme=='https':
                sock=ssl.create_default_context().wrap_socket(sock,server_hostname=self.destination.hostname)
            self.sock=sock
        except Exception:
            sock.close(); raise


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
    def request(self,url,runtime,body=None,headers=None,redirects=True):
        for hop in range(runtime.limits.redirects+1):
            url,addresses=resolve_public(url,runtime)
            c=PinnedConnection(url,addresses,runtime.timeout())
            p=urlsplit(url); path=p.path+('?' +p.query if p.query else '')
            request_headers={'Accept-Encoding':'identity','User-Agent':'Agentnik/0.1'}
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
                    # Avoid echoing upstream error bodies, query strings, or credentials.
                    raise ResearchError(f'Web service HTTP {r.status}; no automatic retry was made')
                ctype=r.getheader('Content-Type','').split(';')[0].strip().lower()
                allowed=('application/json',) if body is not None else ('text/html','text/plain','application/xhtml+xml')
                if ctype not in allowed: raise AccessError('Unsupported web content type')
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


def excerpt(text,size):
    raw=text.encode('utf-8'); clipped=raw[:size].decode('utf-8','ignore')
    return clipped,len(raw)>size


class OllamaWeb:
    """Queries only are sent to Ollama search. Page reads use PublicTransport."""
    def __init__(self,key,transport=None):
        if not isinstance(key,str) or not key.strip(): raise ResearchError('Configure a separate Ollama web-search key first')
        if len(key)>4096 or any(not 33<=ord(ch)<=126 for ch in key):
            raise ResearchError('Search credential must be a single visible ASCII token')
        self.key=key; self.transport=transport or PublicTransport()

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

    def fetch(self,url,runtime):
        final,ctype,payload=self.transport.request(url,runtime)
        text=payload.decode('utf-8','replace'); title=final
        if ctype in ('text/html','application/xhtml+xml'):
            parser=ReadableText(); parser.feed(text)
            text=''.join(parser.parts); title=''.join(parser.title).strip() or final
        text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]','',text)
        text=re.sub(r'[ \t]+',' ',text); text=re.sub(r'\n\s*\n','\n\n',text).strip()
        text,truncated=excerpt(text,8000)
        return [Source('',title[:300],final,text,utc_now(),ctype,truncated,'public-fetch')]

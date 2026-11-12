"""Bounded Parallel specialized search tools for managed research and Code."""
import json
import math
from .tools import AccessError,ResearchError,ToolDefinition
from .web import PublicTransport,resolve_public

DEFINITIONS=(
    ToolDefinition('parallel_place_search','request','Find places near a location with Parallel. JSON string: {"query":"...","location":"..."}, or provide latitude and longitude. Optional open_now, max_distance_km, max_results, mode (fast or advanced).',4000),
    ToolDefinition('parallel_entity_search','request','Find people or companies with Parallel. JSON string: {"entity_type":"people or companies","objective":"..."}; optional match_limit. Results are candidates, not verified matches.',4000),
    ToolDefinition('parallel_image_search','request','Find image URLs and source pages with Parallel. JSON string: {"search_queries":["..."],"objective":"..."}; optional location (country code), max_results, mode (fast or advanced).',4000),
)

class ParallelTools:
    def __init__(self,key,transport=None):
        if not isinstance(key,str) or not key:raise ValueError('Parallel API key is required')
        self.key=key;self.transport=transport or PublicTransport()

    def invoke(self,name,args,runtime):
        if len(self.key)>4096 or any(not 33<=ord(ch)<=126 for ch in self.key):raise ResearchError('Parallel credential must be a single visible ASCII token')
        try:
            raw=args['request'];value=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            if not isinstance(value,dict):raise ValueError()
            if self.key in raw or self.key in json.dumps(value,ensure_ascii=False):raise AccessError('Parallel credential transmission blocked')
            limit=min(runtime.limits.results,20)
            if name=='parallel_place_search':
                if set(value)-{'query','location','latitude','longitude','open_now','max_distance_km','max_results','mode'}:raise ValueError()
                query=value.get('query');location=value.get('location');latitude=value.get('latitude');longitude=value.get('longitude')
                if not isinstance(query,str) or not 1<=len(query.strip())<=200:raise ValueError()
                if location is not None and (not isinstance(location,str) or not 2<=len(location.strip())<=200):raise ValueError()
                if (latitude is None)!=(longitude is None) or (location is None and latitude is None):raise ValueError()
                if latitude is not None:
                    for number,bound in ((latitude,90),(longitude,180)):
                        if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or not -bound<=number<=bound:raise ValueError()
                requested=value.get('max_results',limit)
                if type(requested) is not int or requested<1:raise ValueError()
                limit=min(limit,requested)
                body={'query':query.strip(),'max_results':limit,'mode':value.get('mode','fast')}
                if location is not None:body['location']=location.strip()
                if latitude is not None:body.update(latitude=latitude,longitude=longitude)
                if body['mode'] not in ('fast','advanced'):raise ValueError()
                if 'open_now' in value:
                    if type(value['open_now']) is not bool:raise ValueError()
                    body['open_now']=value['open_now']
                if 'max_distance_km' in value:
                    n=value['max_distance_km']
                    if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not 0<n<=200:raise ValueError()
                    body['max_distance_km']=n
                path='/v1/places/search';field='results'
            elif name=='parallel_image_search':
                if set(value)-{'search_queries','objective','mode','location','max_results'}:raise ValueError()
                queries=value.get('search_queries');objective=value.get('objective','')
                if not isinstance(queries,list) or not 1<=len(queries)<=5 or any(not isinstance(q,str) or not 1<=len(q.strip())<=200 for q in queries) or not isinstance(objective,str) or len(objective)>1000:raise ValueError()
                requested=value.get('max_results',limit)
                if type(requested) is not int or requested<1:raise ValueError()
                limit=min(limit,requested)
                body={'search_queries':[q.strip() for q in queries],'mode':value.get('mode','fast'),'advanced_settings':{'max_results':limit}}
                if 'location' in value:
                    location=value['location']
                    if not isinstance(location,str) or len(location)!=2 or not location.isascii() or not location.isalpha():raise ValueError()
                    body['advanced_settings']['location']=location.lower()
                if body['mode'] not in ('fast','advanced'):raise ValueError()
                if objective.strip():body['objective']=objective.strip()
                path='/v1/images/search';field='results'
            elif name=='parallel_entity_search':
                if set(value)-{'entity_type','objective','match_limit'} or value.get('entity_type') not in ('people','companies') or not isinstance(value.get('objective'),str) or not 1<=len(value['objective'].strip())<=1000:raise ValueError()
                requested=value.get('match_limit',max(5,limit))
                if type(requested) is not int or not 5<=requested<=1000:raise ValueError()
                limit=min(limit,requested);body={'entity_type':value['entity_type'],'objective':value['objective'].strip(),'match_limit':max(5,limit)}
                path='/v1beta/findall/entity-search';field='entities'
            else:raise ValueError()
        except AccessError:raise
        except (ValueError,TypeError,KeyError,RecursionError,UnicodeError):raise ResearchError('Invalid Parallel search request; check the tool description.') from None
        runtime.check()
        _,_,payload=self.transport.request('https://api.parallel.ai'+path,runtime,body=json.dumps(body).encode(),headers={'Content-Type':'application/json','Accept':'application/json','x-api-key':self.key},redirects=False)
        runtime.check()
        try:
            data=json.loads(payload)
            if not isinstance(data,dict) or not isinstance(data.get(field),list) or 'error' in data:raise ValueError()
            if self.key in json.dumps(data,ensure_ascii=False):raise AccessError('Parallel response contains a configured credential')
            result=[]
            for item in data[field][:limit]:
                if not isinstance(item,dict):raise ValueError()
                required=('name','url','description') if name=='parallel_entity_search' else ('title','image_url','source_page_url') if name=='parallel_image_search' else ('name',)
                if any(not isinstance(item.get(k),str) for k in required):raise ValueError()
                # Preserve bounded structured metadata, but never send non-public URLs to the model.
                row={}
                allowed={'name','url','description'} if name=='parallel_entity_search' else {'title','image_url','source_page_url','width','height'} if name=='parallel_image_search' else {'name','url','address','phone','latitude','longitude','distance_km','rating','price_level','opening_hours','timezone','open_now'}
                for k,v in item.items():
                    if k not in allowed or v is None:continue
                    if k in ('url','image_url','source_page_url'):
                        try:v,_=resolve_public(v,runtime)
                        except AccessError:continue
                    if len(json.dumps(v,ensure_ascii=False,allow_nan=False))<=4000:row[k]=v
                result.append(row)
            warnings=data.get('warnings') or []
            if not isinstance(warnings,list):raise ValueError()
            notices=[w.get('message','')[:500] for w in warnings[:5] if isinstance(w,dict) and isinstance(w.get('message'),str)]
        except AccessError:raise
        except (ValueError,TypeError,RecursionError,UnicodeError):raise ResearchError('Malformed Parallel search response') from None
        return {'results':result,'warnings':notices,'notice':'Untrusted Parallel search results; entity matches are not verified. Image URLs are not downloaded.'}

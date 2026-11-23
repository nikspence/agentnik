"""Conservative eligibility for managed fallback after MCP web fetch."""
import json
import re


def mcp_fetch_fallback_urls(result,args,completed_mcp_result=None):
    """Return a public URL only for explicit, non-access MCP fetch failures."""
    if not isinstance(result,dict) or not isinstance(args,dict) or args.get('tool')!='web_fetch':return None
    try:
        params=json.loads(args.get('arguments',''))
        if not isinstance(params,dict) or params.get('allow_live_fetch') is False:return None
        values=[params['url']] if isinstance(params.get('url'),str) else params.get('urls')
        if not isinstance(values,list) or not 1<=len(values)<=20 or any(not isinstance(url,str) for url in values):return None
        from .web import public_url
        urls=list(dict.fromkeys(public_url(url) for url in values))
    except (ValueError,TypeError,RecursionError):return None
    detail=result.get('error','')
    nested=result.get('result')
    structured=nested.get('structuredContent') if isinstance(nested,dict) else None
    if isinstance(structured,dict) and isinstance(structured.get('errors'),list) and structured['errors'] and nested.get('isError') is not True:
        failures=[]
        for item in structured['errors'][:20]:
            if not isinstance(item,dict) or not isinstance(item.get('url'),str):continue
            try:failed_url=public_url(item['url'])
            except ValueError:continue
            reason=json.dumps(item,ensure_ascii=True)
            if re.search(r'\b(?:401|403|407|denied|forbidden|unauthorized|unauthorised|blocked|captcha|challenge|timeout|timed.out|uncertain|cancelled|canceled)\b|may have completed|access restriction',reason,re.I):continue
            if failed_url in urls and failed_url not in failures:failures.append(failed_url)
        return failures or None
    if isinstance(nested,dict) and nested.get('isError') is True:
        parts=[block.get('text','') for block in nested.get('content',[]) if isinstance(block,dict) and isinstance(block.get('text'),str)]
        detail=' '.join(parts)
        if not detail.strip():return None
        try:detail=json.dumps(nested,ensure_ascii=True)
        except (TypeError,ValueError,RecursionError):return None
    elif isinstance(detail,str) and detail.startswith('MCP structured output failed validation:') and isinstance(completed_mcp_result,dict) and completed_mcp_result.get('isError') is not True:
        # The server returned a complete result, but its declared output schema
        # failed validation. Inspect the rejected content for access barriers.
        try:detail=json.dumps(completed_mcp_result,ensure_ascii=True)
        except (TypeError,ValueError,RecursionError):return None
    elif not isinstance(detail,str) or not detail.startswith('MCP tool not found on the selected server:'):
        return None
    if re.search(r'\b(?:401|403|407|denied|forbidden|unauthorized|unauthorised|blocked|captcha|challenge|timeout|timed.out|uncertain|cancelled|canceled)\b|may have completed|access restriction',detail,re.I):return None
    return urls

def mcp_fetch_fallback_url(result,args,completed_mcp_result=None):
    urls=mcp_fetch_fallback_urls(result,args,completed_mcp_result)
    return urls[0] if urls and len(urls)==1 else None


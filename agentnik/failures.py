"""Conservative failure classification. Never infer unsupported tools from generic errors."""
import json
import math
import re
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from .core import EndpointError
from .tools import AccessError,LimitError,UncertainError


def retry_seconds(value):
    if value is None: return .25
    try: seconds=float(value)
    except (ValueError,TypeError):
        try: seconds=(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds()
        except (ValueError,TypeError,OverflowError): return .25
    return max(0,seconds) if math.isfinite(seconds) else .25


def classify(exc,partial=False,tool=''):
    kind='protocol'; status=None; after=None
    if isinstance(exc,InterruptedError): kind='cancelled'
    elif isinstance(exc,AccessError): kind='access'
    elif isinstance(exc,LimitError): kind='limit'
    elif isinstance(exc,UncertainError): kind='uncertain'
    elif isinstance(exc,EndpointError):
        status=exc.status; after=retry_seconds(exc.retry_after)
        payload=exc.payload if isinstance(exc.payload,dict) else {}
        err=payload.get('error',{})
        if isinstance(err,str): message=err; code=param=''
        elif isinstance(err,dict): message=str(err.get('message','')); code=err.get('code',''); param=str(err.get('param',''))
        else: message=code=param=''
        explicit_native=re.fullmatch(r'.+ does not support tools',message) is not None
        explicit_tool=(param.startswith('tools') and (
            code in ('unsupported_tool','unsupported_tool_type') or
            (tool and re.search(r'(?:'+re.escape(tool)+r'(?: calling)?(?: tool)?[\"\']? (?:is )?not supported|does not support (?:the )?'+re.escape(tool)+r'|unsupported tool(?: type)?[: ]+[\"\']?'+re.escape(tool)+r')',message,re.I))))
        if status==400 and (explicit_native or explicit_tool): kind='unsupported'
        elif status==401: kind='authentication'
        elif status==403: kind='access'
        elif status==429: kind='rate_limit'
        elif status==503: kind='temporary'
        elif status in (408,500,502,504): kind='uncertain'
        else: kind='configuration'
    elif isinstance(exc,(OSError,TimeoutError)): kind='uncertain'
    return {'kind':kind,'http_status':status,'retry_after':after,'partial':bool(partial),
            'fallback_allowed':not partial and kind in ('unsupported','authentication','rate_limit','temporary')}

"""Bounded, content-free metrics for coding context and run budgets."""
import json
import math
import time


def serialized_bytes(value):
    # Matches the default JSON encoding used by the model transport; does not
    # include HTTP headers or imply a token count.
    return len(json.dumps(value).encode('utf-8'))


def request_measurement(body):
    groups={'instructions':0,'user_and_history':0,'assistant':0,'tool_results':0,'tool_definitions':0,'other':0}
    for key,value in body.items():
        if key in ('instructions','system'):
            groups['instructions']+=serialized_bytes(value)
        elif key=='tools':groups['tool_definitions']+=serialized_bytes(value)
        elif key in ('messages','input') and isinstance(value,list):
            for item in value:
                if not isinstance(item,dict):groups['other']+=serialized_bytes(item);continue
                role=item.get('role');typ=item.get('type')
                category='tool_results' if role=='tool' or typ in ('function_call_output','tool_result') else 'assistant' if role=='assistant' or typ in ('function_call','reasoning') else 'instructions' if role=='system' else 'user_and_history'
                groups[category]+=serialized_bytes(item)
        else:groups['other']+=serialized_bytes(value)
    return {'json_bytes':serialized_bytes(body),
            'largest_components':[{'category':name,'json_bytes':size} for name,size in sorted(groups.items(),key=lambda pair:(-pair[1],pair[0])) if size][:5]}


def context_usage(runtime,limits,connection,round_number,request_size,reported_input):
    runtime.check()
    token_limit=connection.get('context_limit')
    if type(token_limit) is not int or token_limit<=0:token_limit=None
    if type(reported_input) not in (int,float) or isinstance(reported_input,bool) or not math.isfinite(reported_input) or reported_input<0:reported_input=None
    return {'last_heavy_request':{**request_size,'reported_input_tokens':reported_input,'configured_context_limit_tokens':token_limit},
            'run_budget':{'charged_context_bytes':runtime.context_bytes,'context_bytes_limit':limits.context_bytes,
                          'model_requests_used':runtime.requests,'model_requests_limit':limits.requests,
                          'tool_calls_used':runtime.calls,'tool_calls_limit':limits.calls,
                          'current_tool_round':round_number+1,'tool_rounds_limit':limits.rounds,
                          'elapsed_seconds':round(max(0,time.monotonic()-runtime.started),2),
                          'turn_seconds_limit':limits.turn_seconds},
            'notice':'Request size is serialized JSON bytes, not tokens; component sizes exclude container framing and can include encoded images. Provider input tokens are for the last Heavy request only and may be unavailable. Charged context is a cumulative run budget, not the current model context window. Tool calls in the current batch are charged before execution. This snapshot excludes this tool result and later work.'}

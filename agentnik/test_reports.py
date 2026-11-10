"""Conservative parsing of bounded test command output; never executes commands."""
import re

FORMATS=('auto','unittest','pytest','jest','vitest')


def parse_report(result,format='auto'):
    if format not in FORMATS:raise ValueError('Unsupported test report format')
    text=result['output'];counts={key:None for key in ('total','passed','failed','errors','skipped','expected_failures','unexpected_passes')};detected=None
    ran=list(re.finditer(r'^Ran (\d+) tests? in ',text,re.M));ran=ran[-1] if ran else None
    footer=list(re.finditer(r'^(OK|FAILED)(?: \(([^\n]*)\))?\s*$',text,re.M))
    if format in ('auto','unittest') and ran and footer:
        detected='unittest';last=footer[-1];values={k.strip():int(v) for k,v in re.findall(r'([a-z ]+)=(\d+)',last.group(2) or '')}
        counts.update(total=int(ran.group(1)),failed=values.get('failures',0),errors=values.get('errors',0),skipped=values.get('skipped',0),expected_failures=values.get('expected failures',0),unexpected_passes=values.get('unexpected successes',0))
        counts['passed']=max(0,counts['total']-sum(counts[k] for k in ('failed','errors','skipped','expected_failures','unexpected_passes')))
    if detected is None and format in ('auto','pytest'):
        summaries=[line for line in text.splitlines() if re.search(r'\b\d+ (?:passed|failed|skipped|errors?|xfailed|xpassed)\b',line) and re.search(r'\bin [0-9.]+s',line)]
        if summaries:
            detected='pytest';values={k:int(v) for v,k in re.findall(r'(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)\b',summaries[-1])}
            counts.update(passed=values.get('passed',0),failed=values.get('failed',0),errors=values.get('error',values.get('errors',0)),skipped=values.get('skipped',0),expected_failures=values.get('xfailed',0),unexpected_passes=values.get('xpassed',0))
            counts['total']=None if counts['errors'] else sum(counts[k] for k in ('passed','failed','skipped','expected_failures','unexpected_passes'))
    if detected is None and format in ('auto','jest','vitest'):
        summaries=[line for line in text.splitlines() if re.match(r'^\s*Tests(?::|\s)',line)]
        if summaries:
            line=summaries[-1];kind='jest' if re.match(r'^\s*Tests:',line) else 'vitest'
            total=re.search(r'(\d+) total',line) if kind=='jest' else re.search(r'\((\d+)\)',line)
            values={k:int(v) for v,k in re.findall(r'(\d+) (passed|failed|skipped|todo)\b',line)}
            if total and values and format in ('auto',kind):
                detected=kind;counts.update(total=int(total.group(1)),passed=values.get('passed',0),failed=values.get('failed',0),skipped=values.get('skipped',0)+values.get('todo',0))
    reported_failure=detected=='unittest' and footer[-1].group(1)=='FAILED'
    failures=[];lines=text.splitlines()
    for i,line in enumerate(lines):
        if re.match(r'^\s*(?:FAIL:|FAIL \S|ERROR:|FAILED \S|AssertionError|Error:|[×✕●] )',line):
            failures.append('\n'.join(lines[i:i+4])[:600])
            if len(failures)>=8:break
    outcome='failed' if result['exit_code']!=0 else 'unknown'
    if detected and not result.get('truncated'):
        if reported_failure or (counts['failed'] or 0)+(counts['errors'] or 0)>0:outcome='failed'
        elif result['exit_code']==0:outcome='passed'
    return {'format':detected or 'unrecognized','outcome':outcome,'counts':counts,'complete_output':not result.get('truncated',False),'failures':failures,'notice':'Last recognized summary parsed from command output; not independent verification. Unrecognized or truncated output can leave counts/outcome unknown.'}

"""Versioned session shape checks without rewriting unreadable stored records."""
import copy
import math


class SessionError(ValueError):
    pass

MAX_CODE_ACTIVITY_EVENTS=10_000
MAX_CODE_ACTIVITY_CHARS=4_000_000


def append_code_activity(session,kind,text):
    """Keep a large bounded history and signal a new session version when needed."""
    history=session.setdefault('code_activity',[])
    history.append({'kind':kind,'text':text})
    total=sum(len(item['text']) for item in history)
    removed=[]
    if len(history)>MAX_CODE_ACTIVITY_EVENTS or total>MAX_CODE_ACTIVITY_CHARS:
        target_events=MAX_CODE_ACTIVITY_EVENTS*9//10
        target_chars=MAX_CODE_ACTIVITY_CHARS*9//10
        count=0
        while count<len(history)-1 and (len(history)-count>target_events or total>target_chars):
            total-=len(history[count]['text']);count+=1
        removed=history[:count];del history[:count]
    if len(history)>32:session['version']=5
    return removed


def validate_session(value, ident=None):
    def require(ok):
        if not ok: raise SessionError('Session data is invalid or uses an unsupported version. The stored record has been preserved.')
    require(isinstance(value,dict) and not value.get('_unavailable'))
    data=copy.deepcopy(value)
    require(type(data.get('version',1)) is int and 1<=data.get('version',1)<=5)
    require(isinstance(data.get('id'),str) and bool(data['id']) and (ident is None or data['id']==ident))
    require(data.get('mode') in ('chat','decision','code'))
    if data['mode']!='code':require(data.get('version',1)<=4)
    require(isinstance(data.get('connection'),dict))
    for key in ('url','model','protocol','reasoning','api_key','credential_id'):
        if key in data['connection']: require(isinstance(data['connection'][key],str))
    if 'stream' in data['connection']: require(type(data['connection']['stream']) is bool)
    if 'context_limit' in data['connection']:
        limit=data['connection']['context_limit']; require(type(limit) is int and limit>=0)
    for field,default in [('title','Recovered session'),('connection_name','Saved connection'),('draft','')]:
        data.setdefault(field,default); require(isinstance(data[field],str))
    for field in ('messages','runs','draft_images'):
        data.setdefault(field,[]); require(isinstance(data[field],list))
    require(all(isinstance(p,str) for p in data['draft_images']))
    from .document_reader import validate_documents
    try: validate_documents(data.get('draft_documents', []))
    except ValueError: require(False)
    data.setdefault('form',{}); require(isinstance(data['form'],dict))
    data.setdefault('research_options',{});require(isinstance(data['research_options'],dict))
    options=data['research_options']
    if 'local_tools' in options: require(type(options['local_tools']) is bool)
    if 'enabled' in options: require(type(options['enabled']) is bool)
    if 'policy' in options: require(options['policy'] in (None,'Provider first','Agentnik first','Provider only','Agentnik only'))
    if 'mcp' in options and options['mcp'] is not None:
        ref=options['mcp'];require(isinstance(ref,dict) and set(ref)=={'name','sha256'})
        require(isinstance(ref['name'],str) and 0<len(ref['name'])<=80 and isinstance(ref['sha256'],str) and len(ref['sha256'])==64 and all(ch in '0123456789abcdef' for ch in ref['sha256']))
    if 'limits' in options:
        from .tools import chat_limits
        try: chat_limits(options['limits'])
        except ValueError: require(False)
    if data['mode']=='code':
        require(data.get('version') in (4,5))
        for field in ('project_id','project_name','path_snapshot'): require(isinstance(data.get(field),str) and bool(data[field]))
        require(not data['messages'] and not data['runs'] and 'research_pending' not in data)
        bindings=data.get('coding_models',{});require(isinstance(bindings,dict) and not set(bindings)-{'heavy','light'})
        for binding in bindings.values():
            require(isinstance(binding,dict) and set(binding)=={'connection','model'})
            require(all(isinstance(v,str) and len(v)<=1000 for v in binding.values()))
        activity=data.get('code_activity',[])
        require(isinstance(activity,list) and len(activity)<=(32 if data['version']==4 else MAX_CODE_ACTIVITY_EVENTS))
        require(all(isinstance(e,dict) and isinstance(e.get('kind'),str) and isinstance(e.get('text'),str) and len(e['text'])<=2048 for e in activity))
        require(sum(len(e['text']) for e in activity)<=MAX_CODE_ACTIVITY_CHARS)
        if 'coding_subagents' in data:
            from .subagent_status import validate_records
            try:validate_records(data['coding_subagents'])
            except (ValueError,TypeError):require(False)
        if 'coding_mcp_selection' in data:
            selection=data['coding_mcp_selection'];require(isinstance(selection,dict) and set(selection)=={'primary','extra'})
            primary=selection['primary'];extra=selection['extra'];require(primary is None or isinstance(primary,dict));require(isinstance(extra,list) and len(extra)<=5)
            entries=([primary] if primary is not None else [])+extra;require(len(entries)<=5);names=set()
            for entry in entries:
                require(isinstance(entry,dict) and set(entry)=={'name','sha256'})
                name=entry['name'];digest=entry['sha256']
                require(isinstance(name,str) and bool(name.strip()) and len(name)<=80 and name.casefold() not in names);names.add(name.casefold())
                require(isinstance(digest,str) and len(digest)==64 and all(ch in '0123456789abcdef' for ch in digest))
        if 'coding_skills' in data:
            skills=data['coding_skills'];require(isinstance(skills,list) and len(skills)<=5 and all(isinstance(name,str) and 0<len(name)<=69 for name in skills))
        if 'coding_skill_pins' in data:
            from .project_skills import validate_skill_pins
            try:validate_skill_pins(data.get('coding_skills',[]),data['coding_skill_pins'])
            except (ValueError,TypeError):require(False)
        if 'coding_skill_revisions' in data:
            revisions=data['coding_skill_revisions'];require(isinstance(revisions,list) and len(revisions)<=5)
            for revision in revisions:
                require(isinstance(revision,dict) and set(revision)=={'id','source','sha256'})
                require(isinstance(revision['id'],str) and 0<len(revision['id'])<=69 and revision['source'] in ('repository','user'))
                require(isinstance(revision['sha256'],str) and len(revision['sha256'])==64 and all(ch in '0123456789abcdef' for ch in revision['sha256']))
        if 'coding_skill_history' in data:
            history=data['coding_skill_history'];require(isinstance(history,list) and len(history)<=32)
            run_ids=set()
            for run in history:
                require(isinstance(run,dict) and set(run)=={'run_id','skills'})
                require(isinstance(run['run_id'],str) and 0<len(run['run_id'])<=64 and run['run_id'] not in run_ids);run_ids.add(run['run_id'])
                require(isinstance(run['skills'],list) and len(run['skills'])<=5)
                seen=set()
                for revision in run['skills']:
                    require(isinstance(revision,dict) and set(revision)=={'id','source','sha256'})
                    require(isinstance(revision['id'],str) and 0<len(revision['id'])<=69 and revision['id'] not in seen and revision['source'] in ('repository','user'));seen.add(revision['id'])
                    require(isinstance(revision['sha256'],str) and len(revision['sha256'])==64 and all(ch in '0123456789abcdef' for ch in revision['sha256']))
        for key in ('coding_subagent_model','coding_subagent_model_2'):
            if key in data:
                binding=data[key];require(isinstance(binding,dict) and set(binding)=={'connection','model'})
                require(all(isinstance(v,str) and len(v)<=1000 for v in binding.values()))
        if 'coding_light_enabled' in data: require(type(data['coding_light_enabled']) is bool)
        if 'coding_web_enabled' in data: require(type(data['coding_web_enabled']) is bool)
        if 'coding_advice_enabled' in data: require(type(data['coding_advice_enabled']) is bool)
        if 'coding_decision_model' in data:
            decision=data['coding_decision_model'];require(isinstance(decision,dict) and set(decision)=={'connection','model'})
            require(all(isinstance(value,str) and len(value)<=1000 for value in decision.values()))
        if 'coding_sources' in data:
            sources=data['coding_sources'];require(isinstance(sources,list) and len(sources)<=32)
            for source in sources:
                require(isinstance(source,dict) and set(source)=={'id','title','url'})
                require(all(isinstance(source[key],str) for key in source))
                require(0<len(source['id'])<=16 and len(source['title'])<=200 and len(source['url'])<=2048)
        if 'coding_limits' in data:
            from .code_limits import coding_limits
            try: coding_limits(data['coding_limits'])
            except ValueError: require(False)
        if 'coding_plan' in data:
            from .task_plan import validate_plan
            try:validate_plan(data['coding_plan'])
            except ValueError:require(False)
        if 'coding_working_notes' in data:
            from .code_artifacts import validate_notes
            try:validate_notes(data['coding_working_notes'])
            except (TypeError,ValueError):require(False)
        if 'coding_prompt_history' in data:
            history=data['coding_prompt_history'];require(isinstance(history,list) and len(history)<=100)
            require(all(isinstance(prompt,str) and bool(prompt.strip()) for prompt in history) and sum(map(len,history))<=2_000_000)
        if 'coding_auto_compact' in data:require(type(data['coding_auto_compact']) is bool)
        if 'coding_compaction' in data:
            snapshot=data['coding_compaction'];require(isinstance(snapshot,dict) and set(snapshot)=={'digest','summary'})
            require(isinstance(snapshot['digest'],str) and len(snapshot['digest'])==64 and all(c in '0123456789abcdef' for c in snapshot['digest']))
            require(isinstance(snapshot['summary'],str) and 0<len(snapshot['summary'].strip())<=2048)
        if 'coding_context' in data:
            context=data['coding_context'];require(isinstance(context,dict) and set(context)=={'task','answer'})
            require(all(isinstance(v,str) and len(v)<=2048 for v in context.values()))
        require(data.get('code_state','idle') in ('idle','running','awaiting_approval','completed','failed','cancelled','rejected','timed_out','interrupted'))
        return data
    require(data.get('version',1)<=3)
    def form(value):
        require(isinstance(value,dict))
        require(isinstance(value.get('state',''),str))
        require(isinstance(value.get('images',[]),list) and all(isinstance(p,str) for p in value.get('images',[])))
        require(isinstance(value.get('questions',[]),list))
        for question in value.get('questions',[]):
            require(isinstance(question,dict))
            for field in ('name','type','instructions'): require(isinstance(question.get(field,''),str))
            choices=question.get('choices',[]); require(isinstance(choices,list))
            require(all(isinstance(c,(list,tuple)) and len(c)==2 and all(isinstance(v,str) for v in c) for c in choices))
    form(data['form'])
    def metrics(item):
        require(isinstance(item,dict))
        for counter in item.values():
            require(type(counter) in (int,float,bool) or counter is None)
            if type(counter) in (int,float): require(0<=counter<=2**63-1 and math.isfinite(counter))
    def message(item):
        require(isinstance(item,dict) and item.get('role') in ('user','assistant','system'))
        require(isinstance(item.get('text',''),str)); item.setdefault('text','')
        require(isinstance(item.get('thinking',''),str))
        require(isinstance(item.get('images',[]),list) and all(isinstance(p,str) for p in item.get('images',[])))
        try: validate_documents(item.get('documents', []))
        except ValueError: require(False)
        if 'metrics' in item: metrics(item['metrics'])
        if 'research' in item:
            state=item['research'];require(isinstance(state,dict))
            require(type(state.get('version',1)) is int and 1<=state.get('version',1)<=2)
            for key in ('sources','events','exchanges','response_items','attempts','tool_records','annotations','provider_usage'):
                if key in state: require(isinstance(state[key],list) and all(isinstance(v,dict) for v in state[key]))
    for item in data['messages']: message(item)
    if 'chat_auto_compact' in data:require(data['mode']=='chat' and type(data['chat_auto_compact']) is bool)
    if 'chat_compaction' in data:
        snapshot=data['chat_compaction'];require(data['mode']=='chat' and isinstance(snapshot,dict) and set(snapshot)=={'through','digest','summary'})
        require(type(snapshot['through']) is int and 0<snapshot['through']<=len(data['messages']))
        require(isinstance(snapshot['digest'],str) and len(snapshot['digest'])==64 and all(c in '0123456789abcdef' for c in snapshot['digest']))
        require(isinstance(snapshot['summary'],str) and 0<len(snapshot['summary'].strip())<=16000)
    for run in data['runs']:
        require(isinstance(run,dict) and isinstance(run.get('form'),dict) and isinstance(run.get('result'),dict))
        form(run['form'])
        require(isinstance(run['result'].get('raw'),dict))
        run['result'].setdefault('metrics',{}); metrics(run['result']['metrics'])
    if 'research_pending' in data:
        pending=data['research_pending']; require(isinstance(pending,dict))
        require(isinstance(pending.get('user'),dict) and isinstance(pending.get('result'),dict))
        message(dict(pending['user'],role='user')); message(dict(pending['result'],role='assistant'))
    data.setdefault('version',1)
    return data

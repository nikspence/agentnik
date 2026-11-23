"""Bounded subset of JSON Schema for untrusted MCP input definitions."""
import time
import re
import regex
from contextvars import ContextVar
from jsonschema import Draft202012Validator,Draft7Validator,FormatChecker,validators
from jsonschema.exceptions import ValidationError
from referencing import Registry

SCHEMA_URL='https://json-schema.org/draft/2020-12/schema'
DRAFT7_URLS=('http://json-schema.org/draft-07/schema','https://json-schema.org/draft-07/schema')
ANNOTATIONS={'title','description','default','examples','deprecated','readOnly','writeOnly','$comment','format','discriminator','x-mcp-header','enumNames'}
KEYWORDS=ANNOTATIONS|{'$schema','$defs','definitions','$ref','type','properties','patternProperties','propertyNames','required','additionalProperties','items','prefixItems','additionalItems','uniqueItems','enum','const','minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf','minLength','maxLength','pattern','minItems','maxItems','minProperties','maxProperties','anyOf','oneOf','allOf','if','then','else','dependentRequired','dependentSchemas','dependencies'}
MAX_NODES=1000
MAX_DEPTH=24
MAX_BRANCHES=32
_pattern_deadline=ContextVar('mcp_pattern_deadline',default=0.0)
_choice_cache=ContextVar('mcp_choice_cache',default=None)


def _bounded_pattern(_validator,pattern,instance,_schema):
    if not isinstance(instance,str):return
    remaining=_pattern_deadline.get()-time.monotonic()
    if remaining<=0:raise TimeoutError('MCP pattern validation timed out')
    if regex.search(pattern,instance,timeout=remaining) is None:yield ValidationError('The value does not match the requested pattern.')


def _pattern_matches(pattern,value):
    remaining=_pattern_deadline.get()-time.monotonic()
    if remaining<=0:raise TimeoutError('MCP schema validation timed out')
    return regex.search(pattern,value,timeout=remaining) is not None


def _bounded_pattern_properties(validator,patterns,instance,schema):
    if not validator.is_type(instance,'object'):return
    for pattern,subschema in patterns.items():
        for key,value in instance.items():
            if _pattern_matches(pattern,key):yield from validator.descend(value,subschema,path=key,schema_path=pattern)


def _bounded_property_names(validator,subschema,instance,schema):
    if not validator.is_type(instance,'object'):return
    for key in instance:
        if time.monotonic()>=_pattern_deadline.get():raise TimeoutError('MCP schema validation timed out')
        yield from validator.descend(key,subschema)


def _bounded_additional_properties(validator,additional,instance,schema):
    if not validator.is_type(instance,'object') or additional is True:return
    properties=schema.get('properties',{});patterns=schema.get('patternProperties',{})
    for key,value in instance.items():
        if key in properties or any(_pattern_matches(pattern,key) for pattern in patterns):continue
        if additional is False:
            yield ValidationError('An unexpected property was supplied.');return
        yield from validator.descend(value,additional,path=key)


def _flat_string_choices(variants):
    return isinstance(variants,list) and all(isinstance(item,dict) and 'const' in item and type(item['const']) is str and set(item).issubset({'const','title','description'}) for item in variants)


def _bounded_alternatives(keyword):
    def validate(validator,variants,instance,schema):
        cache=_choice_cache.get();key=id(variants);counts=cache.get(key) if cache is not None else None
        if len(variants)>8 and (counts is not None or _flat_string_choices(variants)):
            if counts is None:
                counts={}
                for item in variants:counts[item['const']]=counts.get(item['const'],0)+1
                if cache is not None:cache[key]=counts
            matches=counts.get(instance,0) if isinstance(instance,str) else 0
            if matches==0 or keyword=='oneOf' and matches!=1:yield ValidationError('The value does not match the requested choices.')
        else:yield from Draft202012Validator.VALIDATORS[keyword](validator,variants,instance,schema)
    return validate


def _unique_item_key(value):
    """Hash JSON values using JSON Schema equality, including nested booleans."""
    if time.monotonic()>=_pattern_deadline.get():raise TimeoutError('MCP schema validation timed out')
    if value is None:return ('null',)
    if type(value) is bool:return ('boolean',value)
    if type(value) in (int,float):return ('number',value)
    if isinstance(value,str):return ('string',value)
    if isinstance(value,list):return ('array',tuple(_unique_item_key(item) for item in value))
    if isinstance(value,dict):return ('object',frozenset((key,_unique_item_key(item)) for key,item in value.items()))
    raise ValueError('Invalid JSON value')


def _bounded_unique_items(validator,unique,instance,schema):
    if not unique or not isinstance(instance,list):return
    seen=set()
    for item in instance:
        key=_unique_item_key(item)
        if key in seen:
            yield ValidationError('The array contains duplicate items.');return
        seen.add(key)


def _validation_deadline():
    if time.monotonic()>=_pattern_deadline.get():raise TimeoutError('MCP schema validation timed out')


def _bounded_if(validator,condition,instance,schema):
    _validation_deadline();matched=validator.evolve(schema=condition).is_valid(instance);_validation_deadline()
    branch='then' if matched else 'else'
    if branch in schema:yield from validator.descend(instance,schema[branch],schema_path=branch)


def _bounded_dependencies(validator,dependencies,instance,schema):
    if not validator.is_type(instance,'object'):return
    for key,dependency in dependencies.items():
        _validation_deadline()
        if key not in instance:continue
        if isinstance(dependency,list):
            for name in dependency:
                _validation_deadline()
                if name not in instance:yield ValidationError('A dependent property is missing.')
        else:yield from validator.descend(instance,dependency,schema_path=key)


_bounded_keywords={'pattern':_bounded_pattern,'patternProperties':_bounded_pattern_properties,'propertyNames':_bounded_property_names,'additionalProperties':_bounded_additional_properties,'oneOf':_bounded_alternatives('oneOf'),'anyOf':_bounded_alternatives('anyOf'),'uniqueItems':_bounded_unique_items,'if':_bounded_if,'dependentRequired':_bounded_dependencies,'dependentSchemas':_bounded_dependencies,'dependencies':_bounded_dependencies}
BOUNDED_2020=validators.extend(Draft202012Validator,_bounded_keywords)
BOUNDED_7=validators.extend(Draft7Validator,_bounded_keywords)


class MCPArgumentValidationError(ValueError):
    """A schema mismatch with value-free feedback for the calling model."""


def _validation_feedback(error):
    path=list(error.absolute_schema_path);fields=[]
    for index,part in enumerate(path[:-1]):
        if part=='properties' and isinstance(path[index+1],str):
            field=path[index+1]
            if field.isascii() and field.isidentifier() and len(field)<=64:fields.append(field)
    if error.validator=='required' and isinstance(error.validator_value,list) and isinstance(error.instance,dict):
        missing=[name for name in error.validator_value if isinstance(name,str) and name not in error.instance and name.isascii() and name.isidentifier() and len(name)<=64]
        if missing:fields.append(missing[0])
    if error.validator in ('dependentRequired','dependencies') and isinstance(error.validator_value,dict) and isinstance(error.instance,dict):
        for trigger,names in error.validator_value.items():
            if trigger in error.instance and isinstance(names,list):
                missing=[name for name in names if isinstance(name,str) and name not in error.instance and name.isascii() and name.isidentifier() and len(name)<=64]
                if missing:fields.append(missing[0]);break
    reasons={'required':'a required field is missing','dependentRequired':'a dependent field is missing','dependencies':'a dependent field is missing','type':'the value has the wrong type','enum':'the value is not an allowed choice','const':'the value does not match the required constant','pattern':'the value does not match the required pattern','minimum':'the value is below the minimum','maximum':'the value is above the maximum','minItems':'the array has too few items','maxItems':'the array has too many items','uniqueItems':'the array contains duplicate items','additionalProperties':'an unexpected field was supplied'}
    reason=reasons.get(error.validator,'a schema constraint was not met')
    location=' for field '+'.'.join(fields[:4]) if fields else ''
    return 'MCP arguments do not match the tool input schema'+location+': '+reason+'.'


def validate_tool_arguments(schema,arguments,check_formats=False):
    """Validate bounded schemas, allowing acyclic local subschema references."""
    if not isinstance(schema,dict) or schema.get('type')!='object' or not isinstance(arguments,dict):raise ValueError('The tool must have an object input schema and JSON object arguments.')
    dialect=schema.get('$schema',SCHEMA_URL)
    if dialect in (SCHEMA_URL,SCHEMA_URL+'#'):validator=Draft202012Validator
    elif dialect in tuple(url+suffix for url in DRAFT7_URLS for suffix in ('','#')):validator=Draft7Validator
    else:raise ValueError('The tool schema uses an unsupported schema version.')
    definitions={key:schema.get(key,{}) for key in ('$defs','definitions')}
    if any(not isinstance(items,dict) for items in definitions.values()) or sum(map(len,definitions.values()))>128:raise ValueError('Invalid tool schema definitions.')

    def resolve(reference):
        # Only traverse schema-bearing keywords, never annotations or remote URIs.
        if not isinstance(reference,str) or not reference.startswith('#/') or '%' in reference:raise ValueError('The tool schema uses unsupported references.')
        parts=reference[2:].split('/')
        if len(parts)>MAX_DEPTH*2:raise ValueError('The tool schema uses unsupported references.')
        decoded=[]
        for part in parts:
            name='';index=0
            while index<len(part):
                if part[index]=='~':
                    if index+1>=len(part) or part[index+1] not in '01':raise ValueError('The tool schema uses unsupported references.')
                    name+='~' if part[index+1]=='0' else '/';index+=2
                else:name+=part[index];index+=1
            decoded.append(name)
        node=schema;pos=0
        while pos<len(decoded):
            if not isinstance(node,dict):raise ValueError('The tool schema has an unresolved reference.')
            key=decoded[pos];pos+=1
            if key in ('properties','patternProperties','dependentSchemas','dependencies','$defs','definitions'):
                if pos>=len(decoded) or not isinstance(node.get(key),dict) or decoded[pos] not in node[key]:raise ValueError('The tool schema has an unresolved reference.')
                node=node[key][decoded[pos]];pos+=1
            elif key in ('anyOf','oneOf','allOf','prefixItems') or (key=='items' and isinstance(node.get(key),list)):
                entries=node.get(key);index=decoded[pos] if pos<len(decoded) else ''
                if not isinstance(entries,list) or len(index)>3 or not index.isascii() or not index.isdigit() or (len(index)>1 and index[0]=='0') or int(index)>=len(entries):raise ValueError('The tool schema has an unresolved reference.')
                node=entries[int(index)];pos+=1
            elif key in ('items','additionalItems','additionalProperties','propertyNames','if','then','else') and key in node:node=node[key]
            else:raise ValueError('The tool schema uses unsupported references.')
        if type(node) is not bool and not isinstance(node,dict):raise ValueError('The tool schema has an unresolved reference.')
        return node

    # Traversing each reference in context catches cycles and bounds repeated work.
    # Combination width is multiplied along each path to cap nested alternatives.
    pending=[(schema,0,1,frozenset())];count=0;pattern_deadline=time.monotonic()+.5
    def validate_pattern(pattern):
        if time.monotonic()>=pattern_deadline:raise ValueError('The tool schema patterns are too complex to validate.')
        if not isinstance(pattern,str) or len(pattern)>512:raise ValueError('The tool schema pattern is invalid or too large.')
        repetitions=1
        for match in re.finditer(r'\{([0-9]*)(?:,([0-9]*))?\}',pattern):
            backslashes=0;position=match.start()-1
            while position>=0 and pattern[position]=='\\':backslashes+=1;position-=1
            if backslashes%2:continue
            upper=match.group(2) or match.group(1) or '0'
            if len(upper)>6:raise ValueError('The tool schema pattern repetition is too large.')
            repetitions*=max(1,int(upper))
            if repetitions>100000:raise ValueError('The tool schema pattern repetition is too large.')
        try:regex.compile(pattern)
        except (regex.error,OverflowError,RecursionError):raise ValueError('The tool schema pattern is invalid.') from None
    while pending:
        node,depth,width,ancestors=pending.pop();count+=1
        if count>MAX_NODES or depth>MAX_DEPTH or width>MAX_BRANCHES:raise ValueError('The tool schema is too complex to validate.')
        if type(node) is bool:continue
        if not isinstance(node,dict):raise ValueError('The tool schema contains an unsupported schema form.')
        ident=id(node)
        if ident in ancestors:raise ValueError('The tool schema uses recursive references.')
        ancestors=ancestors|{ident}
        if not set(node).issubset(KEYWORDS):raise ValueError('The tool schema uses unsupported validation features.')
        if '$schema' in node and node is not schema:raise ValueError('The tool schema uses unsupported nested schema versions.')
        if 'enum' in node and (not isinstance(node['enum'],list) or len(node['enum'])>128):raise ValueError('The tool schema enumeration is too large.')
        if 'pattern' in node:validate_pattern(node['pattern'])
        # format and OpenAPI discriminator are bounded annotations; the
        # JSON Schema validator still enforces every oneOf/type constraint.
        if 'format' in node and (not isinstance(node['format'],str) or not 1<=len(node['format'])<=128):raise ValueError('The tool schema format annotation is invalid.')
        if 'discriminator' in node:
            discriminator=node['discriminator']
            if not isinstance(discriminator,dict) or set(discriminator)-{'propertyName','mapping'}:raise ValueError('The tool schema discriminator annotation is invalid.')
            name=discriminator.get('propertyName');mapping=discriminator.get('mapping',{})
            if not isinstance(name,str) or not 1<=len(name)<=128 or not isinstance(mapping,dict) or len(mapping)>128:raise ValueError('The tool schema discriminator annotation is invalid.')
            for key,reference in mapping.items():
                if not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError('The tool schema discriminator annotation is invalid.')
                resolve(reference)
        for namespace in ('$defs','definitions'):
            if namespace in node:
                if node is not schema:raise ValueError('The tool schema uses unsupported nested definitions.')
                pending.extend((value,depth+1,width,ancestors) for value in definitions[namespace].values())
        if '$ref' in node:pending.append((resolve(node['$ref']),depth+1,width,ancestors))
        properties=node.get('properties',{})
        if not isinstance(properties,dict) or len(properties)>256:raise ValueError('Invalid tool schema properties.')
        pending.extend((value,depth+1,width,ancestors) for value in properties.values())
        patterns=node.get('patternProperties',{})
        if not isinstance(patterns,dict) or len(patterns)>128:raise ValueError('Invalid tool schema pattern properties.')
        for pattern,value in patterns.items():
            validate_pattern(pattern);pending.append((value,depth+1,width,ancestors))
        if 'propertyNames' in node:pending.append((node['propertyNames'],depth+1,width,ancestors))
        for keyword in ('if','then','else'):
            if keyword in node:pending.append((node[keyword],depth+1,width*2,ancestors))
        if validator is Draft7Validator and ('dependentRequired' in node or 'dependentSchemas' in node):raise ValueError('The tool schema uses unsupported dependency keywords for this version.')
        if validator is Draft202012Validator and 'dependencies' in node:raise ValueError('The tool schema uses unsupported dependency keywords for this version.')
        for keyword in ('dependentRequired','dependentSchemas','dependencies'):
            if keyword not in node:continue
            dependencies=node[keyword]
            if not isinstance(dependencies,dict) or len(dependencies)>128:raise ValueError('Invalid tool schema dependencies.')
            for dependency in dependencies.values():
                if keyword=='dependentRequired' or keyword=='dependencies' and isinstance(dependency,list):
                    if not isinstance(dependency,list) or len(dependency)>128:raise ValueError('Invalid tool schema dependencies.')
                else:pending.append((dependency,depth+1,width,ancestors))
        if 'items' in node:
            items=node['items']
            if isinstance(items,list):
                if validator is not Draft7Validator or len(items)>128:raise ValueError('Invalid tool schema tuple items.')
                pending.extend((value,depth+1,width,ancestors) for value in items)
            else:pending.append((items,depth+1,width,ancestors))
        if 'prefixItems' in node:
            items=node['prefixItems']
            if validator is not Draft202012Validator or not isinstance(items,list) or not 1<=len(items)<=128:raise ValueError('Invalid tool schema prefix items.')
            pending.extend((value,depth+1,width,ancestors) for value in items)
        if 'additionalItems' in node:
            if validator is not Draft7Validator:raise ValueError('Invalid tool schema additional items.')
            pending.append((node['additionalItems'],depth+1,width,ancestors))
        extra=node.get('additionalProperties',True)
        if not isinstance(extra,bool):pending.append((extra,depth+1,width,ancestors))
        for keyword in ('anyOf','oneOf','allOf'):
            if keyword in node:
                variants=node[keyword]
                if not isinstance(variants,list) or not variants:raise ValueError('The tool schema has invalid or excessive alternatives.')
                simple_choices=keyword in ('anyOf','oneOf') and _flat_string_choices(variants)
                if len(variants)>8:
                    if not simple_choices or len(variants)>128 or width*len(variants)>128:raise ValueError('The tool schema has invalid or excessive alternatives.')
                    next_width=width
                else:next_width=width*len(variants)
                pending.extend((value,depth+1,next_width,ancestors) for value in variants)
    try:
        validator.check_schema(schema)
        bounded=BOUNDED_7 if validator is Draft7Validator else BOUNDED_2020
        token=_pattern_deadline.set(time.monotonic()+.25);choices_token=_choice_cache.set({})
        try:bounded(schema,registry=Registry(),format_checker=FormatChecker() if check_formats else None).validate(arguments)
        finally:_choice_cache.reset(choices_token);_pattern_deadline.reset(token)
    except TimeoutError:raise ValueError('MCP schema validation timed out.') from None
    except Exception as exc:
        from jsonschema.exceptions import SchemaError
        if isinstance(exc,ValidationError):raise MCPArgumentValidationError(_validation_feedback(exc)) from None
        if isinstance(exc,SchemaError):raise ValueError('The tool input schema is invalid.') from None
        raise ValueError('The tool input schema could not be validated.') from None
    return True


def validate_tool_result(tool,result):
    """Validate structured output when the reviewed tool declares an output schema."""
    if not isinstance(result,dict):raise ValueError('Invalid MCP tool result.')
    if result.get('isError') is True:return True
    if 'output_schema_status' not in tool:return True
    if tool.get('output_schema_status')!='available' or not isinstance(tool.get('output_schema'),dict):
        raise ValueError('MCP output schema is unavailable.')
    if not isinstance(result.get('structuredContent'),dict):
        raise ValueError('MCP tool declared an output schema but did not return a structured object.')
    try:validate_tool_arguments(tool['output_schema'],result['structuredContent'])
    except (ValueError,RecursionError,UnicodeError) as exc:
        if isinstance(exc,MCPArgumentValidationError):raise ValueError('MCP structured result does not match the declared output schema.') from None
        raise ValueError('MCP output schema is invalid or uses unsupported validation features.') from None
    return True

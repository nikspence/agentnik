"""Bounded subset of JSON Schema for untrusted MCP input definitions."""
from jsonschema import Draft202012Validator,Draft7Validator
from referencing import Registry

SCHEMA_URL='https://json-schema.org/draft/2020-12/schema'
DRAFT7_URLS=('http://json-schema.org/draft-07/schema','https://json-schema.org/draft-07/schema')
ANNOTATIONS={'title','description','default','examples','deprecated','readOnly','writeOnly','$comment','format','discriminator'}
KEYWORDS=ANNOTATIONS|{'$schema','$defs','definitions','$ref','type','properties','required','additionalProperties','items','prefixItems','additionalItems','enum','const','minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf','minLength','maxLength','minItems','maxItems','minProperties','maxProperties','anyOf','oneOf','allOf'}
MAX_NODES=1000
MAX_DEPTH=24
MAX_BRANCHES=32


def validate_tool_arguments(schema,arguments):
    """Validate bounded schemas, allowing only acyclic root-local definition references."""
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
            if key in ('properties','$defs','definitions'):
                if pos>=len(decoded) or not isinstance(node.get(key),dict) or decoded[pos] not in node[key]:raise ValueError('The tool schema has an unresolved reference.')
                node=node[key][decoded[pos]];pos+=1
            elif key in ('anyOf','oneOf','allOf','prefixItems') or (key=='items' and isinstance(node.get(key),list)):
                entries=node.get(key);index=decoded[pos] if pos<len(decoded) else ''
                if not isinstance(entries,list) or len(index)>3 or not index.isascii() or not index.isdigit() or (len(index)>1 and index[0]=='0') or int(index)>=len(entries):raise ValueError('The tool schema has an unresolved reference.')
                node=entries[int(index)];pos+=1
            elif key in ('items','additionalItems','additionalProperties') and key in node:node=node[key]
            else:raise ValueError('The tool schema uses unsupported references.')
        if type(node) is not bool and not isinstance(node,dict):raise ValueError('The tool schema has an unresolved reference.')
        return node

    # Traversing each reference in context catches cycles and bounds repeated work.
    # Combination width is multiplied along each path to cap nested alternatives.
    pending=[(schema,0,1,frozenset())];count=0
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
                if not isinstance(variants,list) or not 1<=len(variants)<=8:raise ValueError('The tool schema has invalid or excessive alternatives.')
                pending.extend((value,depth+1,width*len(variants),ancestors) for value in variants)
    try:
        validator.check_schema(schema)
        validator(schema,registry=Registry()).validate(arguments)
    except Exception as exc:
        from jsonschema.exceptions import ValidationError,SchemaError
        if isinstance(exc,ValidationError):raise ValueError('Arguments do not match the tool input schema.') from None
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
        if str(exc)=='Arguments do not match the tool input schema.':raise ValueError('MCP structured result does not match the declared output schema.') from None
        raise ValueError('MCP output schema is invalid or uses unsupported validation features.') from None
    return True

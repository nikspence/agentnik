"""Bounded subset of JSON Schema for untrusted MCP input definitions."""
from jsonschema import Draft202012Validator
from referencing import Registry

SCHEMA_URL='https://json-schema.org/draft/2020-12/schema'
ANNOTATIONS={'title','description','default','examples','deprecated','readOnly','writeOnly','$comment'}
KEYWORDS=ANNOTATIONS|{'$schema','$defs','$ref','type','properties','required','additionalProperties','items','enum','const','minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf','minLength','maxLength','minItems','maxItems','minProperties','maxProperties','anyOf','oneOf','allOf'}
MAX_NODES=1000
MAX_DEPTH=24
MAX_BRANCHES=32


def validate_tool_arguments(schema,arguments):
    """Validate bounded schemas, allowing only acyclic local definition references."""
    if not isinstance(schema,dict) or schema.get('type')!='object' or not isinstance(arguments,dict):raise ValueError('The tool must have an object input schema and JSON object arguments.')
    definitions=schema.get('$defs',{})
    if not isinstance(definitions,dict) or len(definitions)>128:raise ValueError('Invalid tool schema definitions.')

    def resolve(reference):
        # Restrict pointers to a single root definition, with canonical JSON Pointer escapes.
        prefix='#/$defs/'
        if not isinstance(reference,str) or not reference.startswith(prefix):raise ValueError('The tool schema uses unsupported references.')
        pointer=reference[len(prefix):]
        if not pointer or '/' in pointer or '%' in pointer:raise ValueError('The tool schema uses unsupported references.')
        name='';index=0
        while index<len(pointer):
            ch=pointer[index]
            if ch=='~':
                if index+1>=len(pointer) or pointer[index+1] not in '01':raise ValueError('The tool schema uses unsupported references.')
                name+='~' if pointer[index+1]=='0' else '/';index+=2
            else:name+=ch;index+=1
        if name not in definitions:raise ValueError('The tool schema has an unresolved reference.')
        return definitions[name]

    # Traversing each reference in context catches cycles and bounds repeated work.
    # Combination width is multiplied along each path to cap nested alternatives.
    pending=[(schema,0,1,frozenset())];count=0
    while pending:
        node,depth,width,ancestors=pending.pop();count+=1
        if count>MAX_NODES or depth>MAX_DEPTH or width>MAX_BRANCHES:raise ValueError('The tool schema is too complex to validate.')
        if not isinstance(node,dict):raise ValueError('The tool schema contains an unsupported schema form.')
        ident=id(node)
        if ident in ancestors:raise ValueError('The tool schema uses recursive references.')
        ancestors=ancestors|{ident}
        if not set(node).issubset(KEYWORDS):raise ValueError('The tool schema uses unsupported validation features.')
        if '$schema' in node and node['$schema'] not in (SCHEMA_URL,SCHEMA_URL+'#'):raise ValueError('The tool schema uses an unsupported schema version.')
        if 'enum' in node and (not isinstance(node['enum'],list) or len(node['enum'])>128):raise ValueError('The tool schema enumeration is too large.')
        if '$defs' in node:
            if node is not schema:raise ValueError('The tool schema uses unsupported nested definitions.')
            pending.extend((value,depth+1,width,ancestors) for value in definitions.values())
        if '$ref' in node:pending.append((resolve(node['$ref']),depth+1,width,ancestors))
        properties=node.get('properties',{})
        if not isinstance(properties,dict) or len(properties)>256:raise ValueError('Invalid tool schema properties.')
        pending.extend((value,depth+1,width,ancestors) for value in properties.values())
        if 'items' in node:pending.append((node['items'],depth+1,width,ancestors))
        extra=node.get('additionalProperties',True)
        if not isinstance(extra,bool):pending.append((extra,depth+1,width,ancestors))
        for keyword in ('anyOf','oneOf','allOf'):
            if keyword in node:
                variants=node[keyword]
                if not isinstance(variants,list) or not 1<=len(variants)<=8:raise ValueError('The tool schema has invalid or excessive alternatives.')
                pending.extend((value,depth+1,width*len(variants),ancestors) for value in variants)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema,registry=Registry()).validate(arguments)
    except Exception as exc:
        from jsonschema.exceptions import ValidationError,SchemaError
        if isinstance(exc,ValidationError):raise ValueError('Arguments do not match the tool input schema.') from None
        if isinstance(exc,SchemaError):raise ValueError('The tool input schema is invalid.') from None
        raise ValueError('The tool input schema could not be validated.') from None
    return True

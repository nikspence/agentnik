"""Bounded subset of JSON Schema for untrusted MCP input definitions."""
from jsonschema import Draft202012Validator
from referencing import Registry

SCHEMA_URL='https://json-schema.org/draft/2020-12/schema'
ANNOTATIONS={'title','description','default','examples','deprecated','readOnly','writeOnly','$comment'}
KEYWORDS=ANNOTATIONS|{'$schema','type','properties','required','additionalProperties','items','enum','const','minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf','minLength','maxLength','minItems','maxItems','minProperties','maxProperties','anyOf'}


def validate_tool_arguments(schema,arguments):
    """Validate a conservative subset; reject unsupported schema features, never fetch references."""
    if not isinstance(schema,dict) or schema.get('type')!='object' or not isinstance(arguments,dict):raise ValueError('The tool must have an object input schema and JSON object arguments.')
    pending=[(schema,0)];count=0
    while pending:
        node,depth=pending.pop();count+=1
        if count>1000 or depth>24:raise ValueError('The tool schema is too complex to validate.')
        if not isinstance(node,dict):raise ValueError('The tool schema contains an unsupported schema form.')
        if not set(node).issubset(KEYWORDS):raise ValueError('The tool schema uses unsupported validation features.')
        if '$schema' in node and node['$schema'] not in (SCHEMA_URL,SCHEMA_URL+'#'):raise ValueError('The tool schema uses an unsupported schema version.')
        if 'enum' in node and (not isinstance(node['enum'],list) or len(node['enum'])>128):raise ValueError('The tool schema enumeration is too large.')
        if 'anyOf' in node:
            variants=node['anyOf']
            if not isinstance(variants,list) or len(variants)!=2 or not all(isinstance(v,dict) for v in variants) or not any(v=={'type':'null'} for v in variants):raise ValueError('The tool schema uses unsupported validation features.')
            pending.extend((v,depth+1) for v in variants)
        properties=node.get('properties',{})
        if not isinstance(properties,dict) or len(properties)>256:raise ValueError('Invalid tool schema properties.')
        pending.extend((value,depth+1) for value in properties.values())
        if 'items' in node:pending.append((node['items'],depth+1))
        extra=node.get('additionalProperties',True)
        if not isinstance(extra,bool):pending.append((extra,depth+1))
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema,registry=Registry()).validate(arguments)
    except Exception as exc:
        from jsonschema.exceptions import ValidationError,SchemaError
        if isinstance(exc,ValidationError):raise ValueError('Arguments do not match the tool input schema.') from None
        if isinstance(exc,SchemaError):raise ValueError('The tool input schema is invalid.') from None
        raise ValueError('The tool input schema could not be validated.') from None
    return True

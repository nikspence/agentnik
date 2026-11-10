"""Stable managed-search provider identities and independent credentials."""
SEARCH_PROVIDERS={
    'brave':('Brave Search','BRAVE_SEARCH_API_KEY','brave-search'),
    'langsearch':('LangSearch','LANGSEARCH_API_KEY','langsearch-search'),
    'firecrawl':('Firecrawl','FIRECRAWL_API_KEY','firecrawl-search'),
    'firecrawl-keyless':('Firecrawl (keyless)','','firecrawl-keyless-search'),
    'exa':('Exa','EXA_API_KEY','exa-search'),
    'parallel':('Parallel','PARALLEL_API_KEY','parallel-search'),
    'ollama':('Ollama search','OLLAMA_WEB_API_KEY','ollama-search'),
}
SEARCH_KINDS=tuple(SEARCH_PROVIDERS)


def search_ready(spec):
    """Keyless use is explicit; an absent key never changes a keyed profile's mode."""
    return spec.get('kind')=='google' or (spec.get('kind') in SEARCH_KINDS and (spec.get('kind')=='firecrawl-keyless' or bool(spec.get('key'))))


def search_chain(specs):
    """Keep configured order, then add bounded credential-free fallback services."""
    result=[dict(spec) for spec in specs]
    for kind,label in [('firecrawl-keyless','Firecrawl Keyless (automatic fallback)'),('google','Google scrape (automatic fallback)')]:
        if any(spec.get('kind')==kind for spec in result):continue
        ident='builtin-'+kind
        while any(spec.get('id')==ident for spec in result):ident+='-fallback'
        result.append({'id':ident,'kind':kind,'name':label,'key':''})
    return result

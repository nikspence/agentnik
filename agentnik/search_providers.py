"""Stable managed-search provider identities and independent credentials."""
SEARCH_PROVIDERS={
    'brave':('Brave Search','BRAVE_SEARCH_API_KEY','brave-search'),
    'langsearch':('LangSearch','LANGSEARCH_API_KEY','langsearch-search'),
    'firecrawl':('Firecrawl','FIRECRAWL_API_KEY','firecrawl-search'),
    'exa':('Exa','EXA_API_KEY','exa-search'),
    'parallel':('Parallel','PARALLEL_API_KEY','parallel-search'),
    'ollama':('Ollama search','OLLAMA_WEB_API_KEY','ollama-search'),
}
SEARCH_KINDS=tuple(SEARCH_PROVIDERS)

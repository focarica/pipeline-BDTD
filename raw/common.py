"""Constantes compartilhadas do pipeline da BDTD."""

DEFAULT_SEARCH_URL = "https://bdtd.ibict.br/vufind/Search/Results"
DEFAULT_API_BASE_URL = "https://bdtd.ibict.br/vufind/api/v1"
SEARCH_API_URL = f"{DEFAULT_API_BASE_URL}/search"
RECORD_API_URL = f"{DEFAULT_API_BASE_URL}/record"
INITIAL_QUERY_TERMS = ("Computação", "Informática", "Informação")
DEFAULT_PAGE_SIZE = 100

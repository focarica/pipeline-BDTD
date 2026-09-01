"""Utilitários do pipeline de coleta bruta da BDTD."""

from .common import DEFAULT_SEARCH_URL, INITIAL_QUERY_TERMS
from .validation import (
    ValidationReport,
    build_initial_query_url,
    initial_query_params,
    is_valid_pdf_payload,
    validate_pilot_manifest,
)

__all__ = [
    "DEFAULT_SEARCH_URL",
    "INITIAL_QUERY_TERMS",
    "ValidationReport",
    "build_initial_query_url",
    "initial_query_params",
    "is_valid_pdf_payload",
    "validate_pilot_manifest",
]

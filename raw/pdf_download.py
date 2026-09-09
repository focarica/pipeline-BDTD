from __future__ import annotations

from collections.abc import Callable, Mapping
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .http import BdtdAccessError


def direct_pdf_url(record: Mapping[str, Any]) -> str | None:
    urls = record.get("urls")
    if not isinstance(urls, list):
        return None
    for item in urls:
        if not isinstance(item, Mapping):
            continue
        value = item.get("url")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            if ".pdf" in value.casefold() or "download" in value.casefold():
                return value
    return None


def source_url(record: Mapping[str, Any]) -> str:
    urls = record.get("urls")
    if isinstance(urls, list):
        for item in urls:
            if isinstance(item, Mapping):
                value = item.get("url")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def extract_landing_pdf(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        lowered = href.casefold()
        if "bitstream" in lowered and ("download" in lowered or ".pdf" in lowered):
            return urljoin(base_url, href)
    meta = soup.find("meta", attrs={"name": re.compile(r"citation_pdf_url", re.I)})
    content = meta.get("content", "") if meta else ""
    if isinstance(content, str) and content.strip():
        return urljoin(base_url, content.strip())
    for anchor in soup.find_all("a", href=True):
        if str(anchor["href"]).casefold().endswith(".pdf"):
            return urljoin(base_url, str(anchor["href"]))
    return None


def detect_landing_block(html: str) -> tuple[str, str] | None:
    lowered = html.casefold()
    if "anubis" in lowered or "making sure you're not a bot" in lowered:
        return ("landing_antibot", "proteção anti-bot (Anubis) na página da fonte")
    if "grecaptcha" in lowered or "recaptcha" in lowered:
        return ("landing_js_gate", "página exige verificação via reCAPTCHA/JavaScript")
    if "verificando sua sess" in lowered or "enable javascript" in lowered or "habilite o javascript" in lowered:
        return ("landing_js_gate", "página exige JavaScript/verificação de sessão")
    return None


def resolve_pdf_url(
    client: Any,
    record: Mapping[str, Any],
    *,
    record_id: str,
    log: Callable[[str], None] = print,
) -> tuple[str | None, str, str, str]:
    direct = direct_pdf_url(record)
    if direct:
        log(f"{record_id}: PDF direto encontrado na API")
        return (direct, "direct_api_pdf", "URL de PDF direto retornada pela API", "")
    landing_url = source_url(record)
    if not landing_url.startswith(("http://", "https://")):
        log(f"{record_id}: sem URL de origem na API (no_source_url); ignorando")
        return (None, "no_source_url", "registro sem URL de origem na API", "")
    log(f"{record_id}: buscando página da fonte {landing_url}")
    try:
        response = client.request(landing_url)
    except BdtdAccessError as exc:
        status = getattr(exc, "status_code", None)
        detail = f"HTTP {status}" if status else "falha de rede/timeout"
        log(f"{record_id}: página da fonte inacessível ({detail}); ignorando")
        return (None, "landing_unreachable", detail, landing_url)
    content_type = response.headers.get("Content-Type", "")
    if "pdf" in content_type.casefold() and response.content.startswith(b"%PDF-"):
        log(f"{record_id}: página da fonte já é o PDF")
        return (landing_url, "landing_is_pdf", "a URL de origem já retorna o PDF", landing_url)
    block = detect_landing_block(response.text)
    if block:
        reason, detail = block
        log(f"{record_id}: {detail}; ignorando")
        return (None, reason, detail, landing_url)
    resolved = extract_landing_pdf(response.text, landing_url)
    if resolved:
        log(f"{record_id}: PDF resolvido via landing page")
        return (resolved, "landing_resolved", "link de PDF extraído da landing page", landing_url)
    log(f"{record_id}: landing page sem link de PDF; ignorando")
    return (None, "landing_no_pdf_link", "landing page acessível mas sem link de PDF", landing_url)

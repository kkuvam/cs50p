"""
AutoHPO: extract HPO terms from clinical text using a local LLM + Meilisearch.
Provides a Flask blueprint with POST /api/autohpo/suggest.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
from urllib.parse import urlparse

import requests as http_requests
from flask import Blueprint, jsonify, request
from flask_login import login_required
from hpo import search_hpo_memory, search_hpo_results

logger = logging.getLogger(__name__)

autohpo_bp = Blueprint("autohpo", __name__)

HPO_RESULTS_PER_TERM = 5

HPO_SYSTEM_MESSAGE = """\
You are a Clinical Informatics Specialist extracting phenotypic findings from medical narratives for HPO term search.

## Task
Extract atomic clinical findings from the narrative. Output clean medical terms only.

## Rules

### 1. Atomic extraction
- One concept per term
- Split compound phrases: "Hypertension and syncope" -> "Hypertension", "Syncope"

### 2. Deduplication
- Merge repeated concepts; list each unique finding once

### 3. Handle negation (CRITICAL)
- Exclude negated findings completely
- Negation markers: no, denies, absent, negative for, without, never, ruled out
- "No seizures" -> omit "Seizures"

### 4. Normalize terms
- Use standard medical terminology
- Colloquial -> Medical: "racing heart" -> "Tachycardia"
- Preserve clinically significant qualifiers: "Severe intellectual disability" not just "Intellectual disability"

### 5. Output format
- Bare terms only, no parentheses or measurements
- Not: "Hepatomegaly (liver 9 cm)" -> Just: "Hepatomegaly"

### 6. Exclude
- Social history, demographics, medications (unless describing a finding)
- Family history: ignore "mother had", "family history of"
- Extract only the patient's own findings

### 7. Uncertainty
- Include suspected/possible findings

## Output
Return ONLY a numbered list of clinical terms, one per line. No headers, no extra text.
Example:
1. Macrocephaly
2. Developmental delay
3. Tachycardia
"""


def _strip_brackets(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    return s.strip()


def _parse_terms(content: str) -> list[str]:
    """Extract clinical terms from LLM numbered/bulleted list response."""
    terms: list[str] = []
    seen: set[str] = set()
    for line in (content or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Numbered list: "1. Term" / "1) Term"
        m = re.match(r"^\d+[\.\)]\s+(.+)$", line)
        if m:
            candidate = _strip_brackets(m.group(1))
            if candidate:
                key = candidate.lower()
                if key not in seen:
                    seen.add(key)
                    terms.append(candidate)
            continue
        # Bullet list: "- Term" / "* Term"
        m = re.match(r"^[-*]\s+(.+)$", line)
        if m:
            candidate = _strip_brackets(m.group(1))
            if candidate:
                key = candidate.lower()
                if key not in seen:
                    seen.add(key)
                    terms.append(candidate)
            continue
        # Bare line
        candidate = _strip_brackets(line)
        if candidate and not re.match(r"^(#|here|the |i |note)", candidate, re.IGNORECASE):
            key = candidate.lower()
            if key not in seen:
                seen.add(key)
                terms.append(candidate)
    return terms


_ONSITE_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
]
OFFSITE_MESSAGE = (
    "AutoHPO is restricted to an on-site model server; "
    "OPENAI_BASE_URL is not a local or private address."
)


class OffsiteEndpointError(Exception):
    pass


def _is_onsite_url(url: str) -> bool:
    """True only if url is http(s) and its host resolves exclusively to on-site addresses."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 80, proto=socket.IPPROTO_TCP)
        addrs = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
    except (ValueError, OSError):
        return False
    return bool(addrs) and all(any(a in net for net in _ONSITE_NETS) for a in addrs)


def _call_llm(clinical_text: str) -> str:
    """Call local LLM via OpenAI-compatible API. Returns raw response content."""
    base_url = (os.environ.get("OPENAI_BASE_URL") or "http://localhost:1234/v1").rstrip("/")
    model_id = (os.environ.get("OPENAI_MODEL_ID") or "").strip()
    api_key = os.environ.get("OPENAI_API_KEY") or "NA"

    if not _is_onsite_url(base_url):
        logger.warning("AutoHPO refused: OPENAI_BASE_URL is not an on-site address")
        raise OffsiteEndpointError
    url = f"{base_url}/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": HPO_SYSTEM_MESSAGE},
            {"role": "user", "content": clinical_text},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
        "stream": False,
    }
    # Only include model if explicitly set — LM Studio uses whichever model is loaded
    if model_id:
        payload["model"] = model_id

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Ignore HTTP(S)_PROXY env vars so clinical text goes only to the validated host
    session = http_requests.Session()
    session.trust_env = False
    resp = session.post(url, json=payload, headers=headers, timeout=180, allow_redirects=False)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


@autohpo_bp.route("/api/hpo/search")
@login_required
def hpo_search():
    """
    Local HPO search via Meilisearch — replaces external JAX API for Select2.
    GET /api/hpo/search?q=seizure&limit=20
    Returns Select2-compatible {results: [{id, text}]}
    """
    q = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit") or 20), 50)
    if not q:
        return jsonify({"results": []})

    hits = search_hpo_memory(q, limit=limit)
    if not hits:
        hits_ms, _ = search_hpo_results(q, limit=limit)
        hits = hits_ms
    results = []
    for h in hits:
        hpo_id = h.get("hpo_id") or ""
        name = h.get("name") or ""
        defn = h.get("definition") or ""
        short = defn[:90] + "…" if len(defn) > 90 else defn
        text = f"{hpo_id}: {name}"
        if short:
            text += f" – {short}"
        results.append({"id": hpo_id, "text": text})
    return jsonify({"results": results})


@autohpo_bp.route("/api/autohpo/suggest", methods=["POST"])
@login_required
def autohpo_suggest():
    """
    POST JSON: {diagnosis: str, medical_history: str}
    Returns JSON: {terms: [{term, hpo_id, name, definition}]}
    """
    body = request.get_json(silent=True) or {}
    diagnosis = (body.get("diagnosis") or "").strip()
    medical_history = (body.get("medical_history") or "").strip()

    if not diagnosis and not medical_history:
        return jsonify({"error": "diagnosis and/or medical_history required"}), 400

    # Build clinical text for LLM
    parts = []
    if diagnosis:
        parts.append(f"Diagnosis: {diagnosis}")
    if medical_history:
        parts.append(f"Medical History:\n{medical_history}")
    clinical_text = "\n\n".join(parts)

    try:
        llm_response = _call_llm(clinical_text)
    except OffsiteEndpointError:
        return jsonify({"error": OFFSITE_MESSAGE}), 503
    except Exception as exc:
        logger.error("AutoHPO LLM call failed: %s", type(exc).__name__)
        model = (os.environ.get("OPENAI_MODEL_ID") or "").strip()
        if not model or model == "default":
            model = "qwen2.5-coder-7b-instruct-mlx"
        return jsonify(
            {"error": f"AutoHPO model unavailable. Please load the {model} model in LM Studio."}
        ), 503

    terms = _parse_terms(llm_response)
    logger.info("AutoHPO: parsed %d terms", len(terms))

    results = []
    for term in terms:
        hits, _ = search_hpo_results(term, limit=HPO_RESULTS_PER_TERM)
        if hits:
            top = hits[0]
            if top.get("hpo_id"):
                results.append({
                    "term": term,
                    "hpo_id": top["hpo_id"],
                    "name": top.get("name", ""),
                    "definition": top.get("definition", ""),
                })
        else:
            # Include unmatched terms so user sees them (no hpo_id)
            results.append({"term": term, "hpo_id": "", "name": "", "definition": ""})

    return jsonify({"terms": results})

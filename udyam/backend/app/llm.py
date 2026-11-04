"""Gemini (free tier) adapter with a circuit breaker.

Design rules:
  * Every call can fail or be rate limited, so every caller has a deterministic fallback.
  * Prompts carry only the business profile (type, counts, city tier). Never GSTIN, Udyam,
    names on documents or document images. The key is read from the environment, sent as a
    header (not in the URL) and never logged.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from .config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TIMEOUT_S

log = logging.getLogger("udyam.llm")
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_cooldown_until = 0.0
_translate_cache: dict[tuple[str, str], str] = {}

LANG_NAMES = {
    "en": "English", "hi": "Hindi (Devanagari script)", "mr": "Marathi", "ta": "Tamil", "te": "Telugu",
    "bn": "Bengali", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi (Gurmukhi)",
}


def available() -> bool:
    return bool(GEMINI_API_KEY) and time.time() >= _cooldown_until


def status() -> dict:
    return {"configured": bool(GEMINI_API_KEY), "model": GEMINI_MODEL if GEMINI_API_KEY else None,
            "cooling_down": time.time() < _cooldown_until}


def _call(system: str, user: str, *, json_mode: bool, max_tokens: int = 400, temperature: float = 0.3) -> str | None:
    global _cooldown_until
    if not available():
        return None
    gen = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    if "2.5" in GEMINI_MODEL:
        gen["thinkingConfig"] = {"thinkingBudget": 0}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen,
    }
    try:
        r = httpx.post(_URL.format(model=GEMINI_MODEL), json=body, timeout=LLM_TIMEOUT_S,
                       headers={"x-goog-api-key": GEMINI_API_KEY, "content-type": "application/json"})
        if r.status_code == 429 or r.status_code >= 500:
            _cooldown_until = time.time() + 60
            log.warning("gemini unavailable status=%s, falling back for 60s", r.status_code)
            return None
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip() or None
    except Exception as e:  # network, auth, malformed response: the caller falls back
        log.warning("gemini call failed: %s", type(e).__name__)
        _cooldown_until = time.time() + 20
        return None


def extract_json(system: str, user: str) -> dict | None:
    out = _call(system, user, json_mode=True, max_tokens=200, temperature=0.0)
    if not out:
        return None
    try:
        data = json.loads(out)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def explain(context: dict, lang: str) -> str | None:
    """Friendly explanation of a bundle that the rules engine already priced."""
    system = (
        "You are the Accel Business advisor for small-business owners in India. Explain the recommended "
        "bundle in plain, warm language a shop owner understands. Use ONLY the facts in the JSON; never "
        "invent products, prices, discounts or features. Mention the monthly total once. Keep it under 90 words, "
        f"no markdown, no bullet symbols. Reply in {LANG_NAMES.get(lang, 'English')}."
    )
    return _call(system, json.dumps(context, ensure_ascii=False), json_mode=False, max_tokens=300)


def answer(question: str, facts: dict, lang: str) -> str | None:
    system = (
        "You are the Accel Business advisor. Answer the owner's question using ONLY the facts provided. "
        "If the facts do not contain the answer, say you will connect them to a human advisor. Never quote a "
        "price that is not in the facts. Under 70 words, plain text. "
        f"Reply in {LANG_NAMES.get(lang, 'English')}."
    )
    return _call(system, json.dumps({"question": question, "facts": facts}, ensure_ascii=False),
                 json_mode=False, max_tokens=250)


def translate(text: str, lang: str) -> str:
    """Translate fixed UI strings (cached). Falls back to the original text."""
    if lang == "en":
        return text
    key = (text, lang)
    if key in _translate_cache:
        return _translate_cache[key]
    system = (f"Translate the user's text into {LANG_NAMES.get(lang, lang)}. Keep numbers, rupee amounts and "
              "product names unchanged. Output only the translation.")
    out = _call(system, text, json_mode=False, max_tokens=300, temperature=0.0)
    if out:
        _translate_cache[key] = out
        return out
    return text

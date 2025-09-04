# app/llm.py
import json
import time
import logging
import random
import httpx
from typing import Tuple, Optional, Any, Dict

from app.settings import settings

log = logging.getLogger("ms.llm")

# -------------------- Config --------------------
_base = settings.llm_host.rstrip("/")
_gen_url = _base + "/api/generate"

_timeout = float(getattr(settings, "llm_timeout", 10.0))
_qps = max(1, int(getattr(settings, "llm_max_qps", 2)))
_min_delay = 1.0 / _qps
_last_call = 0.0

_MAX_PROMPT_CHARS = int(getattr(settings, "llm_max_prompt_chars", 6000))
_RETRIES = int(getattr(settings, "llm_retries", 2))
_BACKOFF_BASE = float(getattr(settings, "llm_backoff_base", 0.35))  # segundos
_TEMP = float(getattr(settings, "llm_temperature", 0.6))

def _normalize_model_tag(tag: str) -> str:
    if not tag:
        return tag
    aliases = {
        "qwen2.5-vl:3b": "qwen2.5vl:3b",
        "qwen2.5-vl:7b": "qwen2.5vl:7b",
        "qwen2.5-vl": "qwen2.5vl",
    }
    return aliases.get(tag, tag)

_model = _normalize_model_tag(settings.llm_model or "")

# -------------------- Prompts --------------------
_prompt_tpl = (
    "You are a financial relevance filter for Ethereum trading.\n"
    "Given a tweet or a new, answer in compact JSON with fields: "
    "{{\"relevant\": true|false, \"confidence\": float between 0 and 1, "
    "\"labels\": [short tags], \"reason\": \"short reason\"}}.\n"
    "If it is just FOMO, discard it.\n"
    "A tweet or new is relevant if it contains concrete information or sentiment likely to move ETH price, "
    "such as on-chain metrics, major news, technical analysis with actionable claims, protocol changes, ETFs, regulation, "
    "market structure, large flows, whales, hacks, partnerships. Ignore giveaways, memes, generic hype, unrelated coins, spam, discard it if it is not relevant to predict the price of ETH in our context\n"
    "Tweet:\n"
    "{text}\n"
    "JSON:"
)

_polarity_prompt_tpl = (
    "You are a sentiment polarity classifier for crypto trading context.\n"
    "Return strict JSON with fields: "
    "{{\"sentiment_sign\": -1|0|1, \"confidence\": 0..1, \"explanation\": \"short reason\"}}.\n"
    "Use 1 if tone about ETH/market is positive (celebratory profanity is positive), "
    "-1 if negative, 0 if neutral/ambiguous.\n"
    "Text:\n"
    "{text}\n"
    "JSON:"
)

_summary_prompt_tpl = (
    "You are an assistant generating a concise market commentary in natural language for ETH based on structured facts.\n"
    "Write in English, technical, concise, for a trader. Avoid emojis. Return MARKDOWN (no JSON).\n"
    "Facts:\n"
    "{facts}\n\n"
    "Write:\n"
    "- 4–6 lines: price (rango/%), RSI/MACD/ATR (conclusion), momentum vs baseline, "
    "General sentiment)\n"
    "-**Outlook** (bullish/bearish/neutral) + invalidation condition + recomendation\n"
)

# -------------------- Utilidades --------------------
def _rate_limit():
    global _last_call
    now = time.time()
    delta = now - _last_call
    if delta < _min_delay:
        time.sleep(_min_delay - delta)
    _last_call = time.time()

def _clip(text: str, n: int) -> str:
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= n:
        return text
    # intenta cortar en salto de línea para no romper frases
    cut = text[: n - 3]
    nl = cut.rfind("\n")
    if nl > n * 0.6:
        cut = cut[:nl]
    return cut + "..."

def _extract_json(s: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        i = s.find("{")
        j = s.rfind("}")
        if i >= 0 and j > i:
            return json.loads(s[i : j + 1])
    except Exception:
        return None
    return None

def _post_generate(prompt: str, *, num_predict: int) -> Optional[Dict[str, Any]]:
    """
    Llama a Ollama con reintentos y backoff. Devuelve el JSON de Ollama o None.
    """
    payload = {
        "model": _model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": max(16, int(num_predict)),
            "temperature": _TEMP,
        },
    }

    # recortes defensivos
    payload["prompt"] = _clip(payload["prompt"], _MAX_PROMPT_CHARS)

    for attempt in range(_RETRIES + 1):
        try:
            with httpx.Client(timeout=_timeout) as client:
                r = client.post(_gen_url, json=payload)
        except Exception as e:
            log.warning("ollama connect error url=%s model=%s: %s", _gen_url, _model, e)
            r = None

        if r is not None and r.status_code == 200:
            try:
                return r.json()
            except Exception as e:
                log.warning("ollama json decode error: %s", e)
                return None

        # status no-200 → log y retry salvo 404 (modelo no existe)
        if r is not None:
            body = ""
            try:
                body = r.text or ""
            except Exception:
                body = "<no-text>"
            log.warning(
                "ollama status=%s url=%s model=%s body=%s",
                getattr(r, "status_code", "NA"),
                _gen_url,
                _model,
                body[:200],
            )
            if r.status_code == 404:
                # No insistas si el modelo no está
                return None

        if attempt < _RETRIES:
            # backoff exponencial con jitter
            sleep_s = (_BACKOFF_BASE * (2**attempt)) * (0.7 + 0.6 * random.random())
            time.sleep(sleep_s)

    return None

# -------------------- API pública --------------------
def classify(text: str):
    """
    Filtro de relevancia (tweet/news) → (relevant: bool, confidence: float, labels: list, reason: str)
    """
    _rate_limit()
    data = _post_generate(_prompt_tpl.format(text=text), num_predict=80)
    if not data:
        return True, 1.0, [], "fallback_llm_unavailable"
    resp = data.get("response") or ""
    obj = _extract_json(resp)
    if not isinstance(obj, dict):
        return True, 1.0, [], "fallback_llm_badjson"
    rel = bool(obj.get("relevant", True))
    conf = float(obj.get("confidence", 1.0))
    labels = obj.get("labels") or []
    if not isinstance(labels, list):
        labels = []
    reason = obj.get("reason") or ""
    return rel, conf, labels, reason

def polarity(text: str) -> Tuple[int, float, str]:
    """
    Clasifica el signo del tono: -1, 0, 1
    """
    _rate_limit()
    data = _post_generate(_polarity_prompt_tpl.format(text=text), num_predict=60)
    if not data:
        return 0, 0.0, "fallback_llm_unavailable"
    resp = data.get("response") or ""
    obj = _extract_json(resp)
    if not isinstance(obj, dict):
        return 0, 0.0, "fallback_llm_badjson"
    try:
        sign = int(obj.get("sentiment_sign", 0))
    except Exception:
        sign = 0
    if sign not in (-1, 0, 1):
        sign = 0
    conf = float(obj.get("confidence", 0.0) or 0.0)
    expl = obj.get("explanation") or ""
    return sign, conf, expl

def summarize(facts_text: str) -> str:
    """
    Resumen breve en Markdown para el dashboard.
    """
    _rate_limit()
    data = _post_generate(_summary_prompt_tpl.format(facts=facts_text), num_predict=220)
    if not data:
        return "Comentario no disponible: LLM no responde."
    resp = (data.get("response") or "").strip()
    return resp or "Comentario no disponible."

# (Opcional) utilidad genérica por si la quieres usar en otros sitios
def simple_generate(prompt: str, *, num_predict: int = 128) -> Tuple[bool, str]:
    _rate_limit()
    data = _post_generate(prompt, num_predict=num_predict)
    if not data:
        return False, ""
    return True, (data.get("response") or "").strip()

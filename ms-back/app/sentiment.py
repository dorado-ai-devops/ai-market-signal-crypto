from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import numpy as np
from app.settings import settings
from app import llm

_finbert = "ProsusAI/finbert"
_tw = "cardiffnlp/twitter-roberta-base-sentiment-latest"

_fin_tok = AutoTokenizer.from_pretrained(_finbert)
_fin_mod = AutoModelForSequenceClassification.from_pretrained(_finbert)
_tw_tok = AutoTokenizer.from_pretrained(_tw)
_tw_mod = AutoModelForSequenceClassification.from_pretrained(_tw)

def _score(model, tokenizer, text, max_len):
    with torch.no_grad():
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=max_len)
        logits = model(**inputs).logits[0].detach().cpu().numpy()
    probs = np.exp(logits) / np.exp(logits).sum()
    s = float(probs[-1] - probs[0])
    if s > 1.0:
        s = 1.0
    if s < -1.0:
        s = -1.0
    return s

def _apply_llm_sign(base: float, text: str) -> float:
    # Permite desactivar el ajuste de signo por LLM vía settings
    if not bool(getattr(settings, "llm_sentiment_use", True)):
        return float(base)

    sign, conf, _ = llm.polarity(text)
    min_conf = float(getattr(settings, "llm_sentiment_min_conf", 0.7))

    # Si el LLM está seguro, usamos su signo (o 0 para neutral) sobre el módulo del score base
    if conf >= min_conf and sign in (-1, 0, 1):
        if sign == 0:
            return 0.0
        return float(sign) * abs(float(base))

    # Si no está seguro, mantenemos el score base
    return float(base)

def score_fin(text: str) -> float:
    base = _score(_fin_mod, _fin_tok, text, 256)
    return _apply_llm_sign(base, text)

def score_tweet(text: str) -> float:
    base = _score(_tw_mod, _tw_tok, text, 128)
    return _apply_llm_sign(base, text)

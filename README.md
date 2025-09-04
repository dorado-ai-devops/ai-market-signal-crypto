# Market Signal — Resumen del proyecto

Breve: Market Signal es una plataforma modular para ingestión de señales de mercado (RSS, X/twitter), scoring de sentimiento (Transformers), clasificación de relevancia (LLM), cálculo de impacto y generación de señales operacionales. Expone una API FastAPI y una SPA React para visualización operacional.

Contenido del repositorio
- `ms-back/` — Backend Python (FastAPI, SQLAlchemy). Ingestores, modelos de ML, lógica de señales, prices, eventos SSE y endpoints.
- `ms-front/` — Frontend React + TypeScript (Vite). Dashboard operativo con SSE/polling, gráficos y tabla de items.

Quick start (local)

Backend (desde la raíz):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r ms-back/requirements.txt
# Copiar/editar ms-back/env.example -> ms-back/.env y ajustar variables (DB_PATH, LLM_HOST, TWAPI_API_KEY...)
cd ms-back
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd ms-front
pnpm install
# Crear .env con VITE_API_BASE y VITE_USE_MOCK
pnpm dev
```

Arquitectura y flujo de datos (resumen)
- Ingestores (`ms-back/app/ingestors`): RSS y X/twitter.
- Preprocesado: normalización de texto, dedupe por hash, reglas anti-spam/shill.
- Scoring: modelos Transformers locales (`finbert` y `twitter-roberta`) devuelven score en [-1,1].
- LLM: cliente HTTP que clasifica relevancia/polaridad y genera resúmenes (prompt-driven, rate-limited).
- Almacenamiento: SQLite con SQLAlchemy (`items`, `signals`, `prices`). `init_db()` aplica migraciones suaves.
- Cálculo de impacto: mide retorno futuro (15m/60m) normalizado por volatilidad histórica.
- Señalización: `compute_once()` calcula `ema15`, menciones, indicadores de precio (RSI/MACD/ATR/VWAP) y combina todo en `alpha` para decidir `action`.
- Exposición: API REST (estado, items, signals, metrics, series) y SSE (`/events`) para UI.

Modelos y LLM
- Transformadores (on-device):
  - `ProsusAI/finbert` → `score_fin()`
  - `cardiffnlp/twitter-roberta-base-sentiment-latest` → `score_tweet()`
- LLM externo (configurable `LLM_HOST`) usado para: relevancia (`classify`), polaridad (`polarity`) y resúmenes (`summarize`).

Datos y representación
- `items`: id (sha256), source, asset, ts, text, score, label, llm_* fields, impact, impact_meta, url.
- `signals`: id, asset, ts, ema15, mentions, action, price indicators opcionales.
- `prices`: OHLCV por timeframe.

API principal (ejemplos)
- `GET /health`
- `GET /api/state` — estado actual
- `GET /api/signals?limit=200`
- `GET /api/items?limit=100`
- `GET /api/metrics`
- `GET /events` — SSE
- `GET /api/summary` — resumen generado por SLM

Variables de configuración
- `DB_PATH`, `POLL_SECONDS`, `RSS_FEEDS`, `X_QUERY`
- Twitter: `TWAPI_API_KEY`, `TWAPI_BASE`, filtros (min likes/rts/replies)
- LLM: `LLM_HOST`, `LLM_MODEL`, `LLM_ENABLED`, `LLM_TIMEOUT`, `LLM_MAX_QPS`, `LLM_MIN_CONF`
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Thresholds y pesos: `alpha_threshold_up/down`, `alpha_w_*` (ajustables en `settings.py`).




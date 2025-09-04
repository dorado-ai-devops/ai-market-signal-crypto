Prerrequisitos
# market-signal

Prerrequisitos

- Crear bot de Telegram y obtener `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` si desea notificaciones.

Comandos básicos

- make build && make run
- Probar health endpoint con:

```bash
curl -f http://localhost:8000/health
```

Despliegue en k3s (local)

- make build && make k-load && make k-apply && make k-port

Notas de calibración

- Dejar correr 7 días para que el baseline se estabilice. Ajustar umbrales si se generan alertas falsas o faltan señales. Cambiar `POLL_SECONDS` en ConfigMap o `.env` para mayor o menor frecuencia.

Helm

Para desplegar con Helm localmente:

```bash
helm install market-signal ./helm --set image.repository=market-signal --set image.tag=latest
```

Para desinstalar:

```bash
helm uninstall market-signal
```

Argo CD

Coloque este repositorio en un control de versiones accesible por Argo CD. Cree una Application con el manifiesto `k8s/argocd-app.yaml`, rellenando `spec.source.repoURL` con la URL del repo.
Argo CD sincronizará la carpeta `helm` y desplegará el chart. Configure los valores/secretos en ArgoCD o en el cluster (Secrets/ConfigMaps) según necesite.

---

## Resumen del código (módulos Python)

Este proyecto contiene una aplicación de ingestión y señalización de mercado (market-signal). A continuación se describe la estructura y responsabilidades de los módulos Python en `app/` y `app/ingestors/`.

Formato: `archivo` — propósito y funciones principales.

- `app/__init__.py` — Inicializa el paquete (vacío). La lógica principal está en `app/main.py`.

- `app/main.py` — Punto de entrada FastAPI. Define el ciclo de vida (lifespan) que:
	- Inicializa logging y la base de datos.
	- Lanza hilos demonio para: ingestión RSS (`rss_loop`), ingestión X/twitter (`x_loop`) y cálculo de señales (`signal_loop`).
	- Expone endpoints HTTP para estado, señales, items, métricas, configuración LLM y control del nivel de log.

- `app/llm.py` — Cliente HTTP para un LLM (por defecto `LLM_HOST`).
	- Construye un prompt que solicita un JSON con `relevant`, `confidence`, `labels`, `reason` para clasificar textos.
	- Implementa rate-limiting básico y extracción tolerante de JSON.
	- Función pública: `classify(text: str) -> (relevant: bool, confidence: float, labels: list, reason: str)`.

- `app/schemas.py` — Modelos Pydantic para respuestas de la API: `State`, `SignalOut`, `ItemOut`, `Metrics`.

- `app/sentiment.py` — Wrappers de Transformers para scoring:
	- `score_fin(text: str)` usa `ProsusAI/finbert`.
	- `score_tweet(text: str)` usa `cardiffnlp/twitter-roberta-base-sentiment-latest`.

- `app/settings.py` — Configuración con Pydantic Settings: feeds RSS, `x_query`, `poll_seconds`, `asset`, `db_path`, parámetros de Twitter API, LLM y Telegram.

- `app/signal.py` — Cálculo de señales:
	- `compute_once()` lee items recientes, calcula EMA (ema15) sobre scores, cuenta menciones y decide `action` (`hold`/`accumulate`/`wait`).
	- Persiste señales en `signals` y envía notificaciones Telegram si procede.

- `app/storage.py` — SQLAlchemy + SQLite:
	- Define `Item` y `Signal` y funciones `init_db()` y `get_session()`.
	- `init_db()` crea tablas y añade columnas LLM de forma idempotente si faltan.

- `app/ingestors/__init__.py` — Paquete de ingestors (vacío, sirve para importar submódulos).

- `app/ingestors/rss.py` — Ingestor RSS:
	- Parseo de feeds configurados en `settings.rss_feeds`, evita duplicados, calcula `score_fin` y guarda `Item` con label `news`.

- `app/ingestors/x_search_io.py` — Ingestor para X/twitter via `twitterapi.io`:
	- Reglas heurísticas de filtrado (likes, rts, replies, longitud, hashtags, shill words, ratios, etc.).
	- Normaliza tweets, opcionalmente llama a LLM (`app.llm.classify`) para filtrar por relevancia.
	- Calcula `score_tweet`, guarda `Item` con label `tweet` y campos LLM.
	- Implementa backoff y logging de métricas por ejecución.

## Contrato mínimo (inputs/outputs)

- Entrada: datos de origen (RSS, X/twitter) y configuración en `.env`/variables.
- Salida: base de datos SQLite con tablas `items` y `signals`; API HTTP para consultar estado, señales, items y métricas.

## Cómo ejecutar localmente (rápido)

1. Crear entorno virtual e instalar dependencias:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Crear o revisar `.env` con parámetros importantes (`DB_PATH`, `LLM_HOST`, `TWAPI_API_KEY`, etc.).

3. Ejecutar la API (con uvicorn):

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4. Probar endpoint de salud:

```bash
curl -f http://localhost:8000/health
```

Notas y consideraciones

- Los modelos en `app/sentiment.py` descargan pesos grandes; asegúrese de tener ancho de banda/espacio y, si es necesario, soporte de GPU.
- Si no dispone de `TWAPI_API_KEY`, la ingestión desde X fallará; RSS seguirá funcionando.
- El LLM es opcional: `LLM_ENABLED` controla si se llama a `app.llm.classify()` desde el ingestor de X.

## Archivos relevantes

- `helm/` — Chart Helm para Kubernetes.
- `k8s/argocd-app.yaml` — Manifiesto de Argo CD.

## Cobertura de la tarea

- Leer archivos Python en `market-signal` y generar un README resumido: Done.

---
Pequeños siguientes pasos sugeridos (opcionales): añadir ejemplos de `.env`, tests unitarios para `signal.ema()` y un script de inicialización de DB.

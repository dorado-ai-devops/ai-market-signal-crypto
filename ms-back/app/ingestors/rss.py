import feedparser, hashlib, time, re, logging, json, html
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from app.storage import get_session, Item
from app.sentiment import score_fin
from app.settings import settings
from app import events

try:
    from app.llm import classify as llm_classify
except Exception:
    llm_classify = None

log = logging.getLogger("ms.rss")

# Config más permisiva por defecto (override por settings)
RSS_FEEDS = list(getattr(settings, "rss_feeds", []))
POLL_SECONDS = int(getattr(settings, "poll_seconds", 60))
WINDOW_MIN = int(getattr(settings, "rss_window_min", 0))  # 0 = sin filtro por ventana
REQUIRE_TOKEN_MATCH = bool(getattr(settings, "rss_require_token_match", False))  # relajado
LLM_ENABLED = bool(getattr(settings, "llm_enabled", False))
LLM_MIN_CONF = float(getattr(settings, "llm_min_conf", 0.6))
BACKOFF_MAX = int(getattr(settings, "rss_backoff_max", 300))
MIN_TEXT_LEN = int(getattr(settings, "rss_min_text_len", 16))  # más laxo
MAX_URLS = int(getattr(settings, "rss_max_urls", 20))          # más laxo
DEBUG = bool(getattr(settings, "rss_debug", False))

# Relevancia
_TOKEN_RE = re.compile(r'(?i)(?<![A-Za-z])ETH(?![A-Za-z])|\$ETH|Ethereum')
_URL_RE = re.compile(r"https?://\S+|www\.\S+")

_last_useful_ts = 0.0
_backoff = 0

def _snip(s: str, n: int = 160) -> str:
    if not s:
        return ""
    s = s.replace("\n"," ").replace("\r"," ").strip()
    return (s[:n] + "…") if len(s) > n else s

def _strip_html(s: str) -> str:
    if not s:
        return ""
    # elimina tags simples
    s = re.sub(r"<[^>]+>", " ", s)
    # unescape entidades HTML
    s = html.unescape(s)
    # normaliza espacios
    return " ".join(s.split())

def _extract_text(entry) -> str:
    title = getattr(entry, "title", "") or ""
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    content_val = ""
    try:
        contents = getattr(entry, "content", None)
        if isinstance(contents, list) and contents:
            content_val = contents[0].get("value") or ""
    except Exception:
        content_val = ""
    raw = f"{title} {summary} {content_val}".strip()
    return _strip_html(raw)

def _clean_text(s: str) -> str:
    return " ".join((s or "").replace("\n"," ").replace("\r"," ").split())

def _parse_pub_dt(e) -> datetime:
    ts = None
    dtp = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
    if dtp:
        try:
            ts = datetime(*dtp[:6], tzinfo=timezone.utc)
        except Exception:
            ts = None
    if not ts:
        v = getattr(e, "published", None) or getattr(e, "updated", None)
        if v:
            try:
                ts = datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(timezone.utc)
            except Exception:
                ts = None
    return ts or datetime.now(timezone.utc)

def _fresh_enough(ts: datetime) -> bool:
    if WINDOW_MIN <= 0:
        return True
    return ts >= datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MIN)

def _url_domain_has_eth(link: str | None) -> bool:
    if not link:
        return False
    try:
        u = urlparse(link)
        host_path = f"{u.netloc}{u.path}".lower()
        return ("eth" in host_path) or ("ethereum" in host_path)
    except Exception:
        return False

def _tags_include_eth(entry) -> bool:
    try:
        tags = getattr(entry, "tags", None)
        if not isinstance(tags, list):
            return False
        for t in tags:
            term = (t.get("term") if isinstance(t, dict) else getattr(t, "term", None)) or ""
            if _TOKEN_RE.search(term or ""):
                return True
    except Exception:
        pass
    return False

def _is_relevant(text: str, entry) -> bool:
    if not REQUIRE_TOKEN_MATCH:
        return True
    clean = _clean_text(text)
    if _TOKEN_RE.search(clean):
        return True
    # Relevancia flexible adicional cuando se exige token
    if _tags_include_eth(entry):
        return True
    link = getattr(entry, "link", None)
    if _url_domain_has_eth(link):
        return True
    return False

def _is_noise(text: str) -> bool:
    if not text:
        return True
    clean = _clean_text(text)
    if len(clean) < MIN_TEXT_LEN:
        # Acepta textos cortos si hay al menos una URL válida
        urls = _URL_RE.findall(text or "")
        return len(urls) == 0
    urls = _URL_RE.findall(text or "")
    if len(urls) > MAX_URLS:
        return True
    return False

def run_once() -> int:
    global _last_useful_ts, _backoff
    s = get_session()
    inserted = 0
    useful = False
    seen = kept = 0
    skip_dupe = skip_empty = skip_noise = skip_token = skip_window = skip_llm = 0

    try:
        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
            except Exception as e:
                log.warning(f"rss parse error url={feed_url} err={e}")
                continue

            entries = getattr(feed, "entries", []) or []
            for e in entries:
                seen += 1
                link = getattr(e, "link", None)
                text = _extract_text(e)
                if not text:
                    skip_empty += 1
                    if DEBUG: log.debug(f"drop empty url={feed_url}")
                    continue

                uid_src = link or getattr(e, "id", None) or getattr(e, "guid", None) or _snip(text, 64)
                uid = hashlib.sha256((uid_src or "").encode()).hexdigest()
                if s.get(Item, uid):
                    skip_dupe += 1
                    continue

                ts = _parse_pub_dt(e)
                if not _fresh_enough(ts):
                    skip_window += 1
                    if DEBUG: log.debug(f"drop stale ts={ts.isoformat()} title='{_snip(getattr(e,'title',''))}'")
                    continue

                if _is_noise(text):
                    skip_noise += 1
                    if DEBUG: log.debug(f"drop noise title='{_snip(getattr(e,'title',''))}'")
                    continue

                if not _is_relevant(text, e):
                    skip_token += 1
                    if DEBUG: log.debug(f"drop no_token title='{_snip(getattr(e,'title',''))}'")
                    continue

                # LLM opcional y blando
                llm_rel = None
                llm_conf = None
                llm_labels = None
                llm_reason = None
                if LLM_ENABLED and llm_classify:
                    try:
                        rel, llm_score, labels, reason = llm_classify(text)
                        llm_rel = bool(rel)
                        llm_conf = float(llm_score)
                        llm_labels = ",".join(labels or []) if isinstance(labels, list) else None
                        llm_reason = reason or None
                    except Exception as ex:
                        llm_rel = True
                        llm_conf = 1.0
                        llm_labels = None
                        llm_reason = f"llm_error:{ex}"
                    if (not llm_rel) or (llm_conf is not None and llm_conf < LLM_MIN_CONF):
                        skip_llm += 1
                        if DEBUG: log.debug(f"drop llm conf={llm_conf} title='{_snip(getattr(e,'title',''))}'")
                        continue

                kept += 1
                score = score_fin(text)
                impact_meta = {
                    "title": getattr(e, "title", None),
                    "published": getattr(e, "published", None) or getattr(e, "updated", None),
                    "author": getattr(e, "author", None),
                    "feed": getattr(feed, "feed", {}).get("title") if isinstance(getattr(feed, "feed", {}), dict) else None
                }

                s.add(Item(
                    id=uid, source="rss", asset=settings.asset, ts=ts,
                    text=text, score=score, label="news",
                    llm_relevant=llm_rel, llm_score=llm_conf, llm_labels=llm_labels, llm_reason=llm_reason,
                    url=link, impact_meta=json.dumps({k: v for k, v in impact_meta.items() if v})
                ))
                inserted += 1
                useful = True

                if getattr(settings, "rss_emit_per_item", False):
                    events.emit("item", "rss item inserted", {"source": "rss", "score": round(score, 3)})

        s.commit()
    finally:
        s.close()

    now = time.time()
    if useful:
        _last_useful_ts = now
        _backoff = 0
    else:
        _backoff = min(BACKOFF_MAX, _backoff + max(1, int(POLL_SECONDS / 2)))

    log.info(
        f"rss seen={seen} kept={kept} inserted={inserted} "
        f"skips[dupe={skip_dupe}, empty={skip_empty}, noise={skip_noise}, token={skip_token}, win={skip_window}, llm={skip_llm}] "
        f"window_min={WINDOW_MIN} require_token={REQUIRE_TOKEN_MATCH} backoff={_backoff}"
    )

    events.emit("item", f"{inserted} rss items inserted (batch)", {
        "count": inserted,
        "source": "rss",
        "seen": seen,
        "kept": kept,
        "skips": {
            "dupe": skip_dupe, "empty": skip_empty, "noise": skip_noise,
            "token": skip_token, "window": skip_window, "llm": skip_llm
        }
    })
    return inserted

def loop():
    global _backoff
    while True:
        try:
            run_once()
        except Exception as e:
            log.error(f"rss loop error: {e}")
        sleep_for = max(POLL_SECONDS, 5) + _backoff
        time.sleep(sleep_for)

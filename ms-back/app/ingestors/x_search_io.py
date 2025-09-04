# app/ingestors/x_search_io.py
import re, time, hashlib, logging
from datetime import datetime, timezone, timedelta
import httpx
from app.storage import get_session, Item
from app.settings import settings
from app.sentiment import score_tweet
from app import events

try:
    from app.llm import classify as llm_classify
except Exception:
    llm_classify = None

log = logging.getLogger("ms.x")

TWAPI_BASE = settings.twapi_base.rstrip("/")
TWAPI_API_KEY = settings.twapi_api_key or ""
MAX_PER_RUN = settings.twapi_max_per_run
MIN_LIKES = settings.twapi_min_likes
MIN_RTS = max(0, settings.twapi_min_rts)
MIN_REPLIES = settings.twapi_min_replies
WINDOW_MIN = settings.twapi_window_min
BACKOFF_MAX = settings.twapi_backoff_max
DEBUG = bool(getattr(settings, "twapi_debug", False))
PAGES_PER_RUN = int(getattr(settings, "twapi_pages_per_run", 1))
QPS_SECONDS = int(getattr(settings, "twapi_qps_seconds", 6))
REQUIRE_TOKEN_MATCH = bool(getattr(settings, "twapi_require_token_match", True))
EXCLUDE_QUOTES = bool(getattr(settings, "twapi_exclude_quotes", True))
LLM_ENABLED = bool(getattr(settings, "llm_enabled", False))
LLM_MIN_CONF = float(getattr(settings, "llm_min_conf", 0.6))

#Anti-spam
MIN_TEXT_LEN = int(getattr(settings, "twapi_min_text_len", 20))
MAX_HASHTAGS = int(getattr(settings, "twapi_max_hashtags", 6))
MAX_MENTIONS = int(getattr(settings, "twapi_max_mentions", 4))
MAX_URLS = int(getattr(settings, "twapi_max_urls", 3))
ALLOW_ONLY_ETH_CASHTAG = bool(getattr(settings, "twapi_allow_only_eth_cashtag", True))
MAX_UPPER_RATIO = float(getattr(settings, "twapi_max_upper_ratio", 0.7))
MAX_SYMBOL_RATIO = float(getattr(settings, "twapi_max_symbol_ratio", 0.3))
_SHILL_DEFAULT = [
    "airdrop","giveaway","presale","pre-sale","wl","whitelist","join","pump","moon","gem",
    "alpha","ref","referral","telegram","discord","tg","claim","mint","launch now","buy now","fomo"
]
_SHILL_WORDS = set(getattr(settings, "twapi_shill_words", _SHILL_DEFAULT))

# Logging detallado
DETAIL = bool(getattr(settings, "twapi_log_details", False)) or DEBUG
SNIP = int(getattr(settings, "twapi_log_snippet_len", 160))

# Emisión de eventos por tweet (evita spamear UI por defecto)
EMIT_PER_TWEET = bool(getattr(settings, "twapi_emit_per_tweet", False))

_last_useful_ts = 0.0
_backoff = 0

_HASHTAG_RE = re.compile(r"#\w+")
_MENTION_RE = re.compile(r"@[A-Za-z0-9_]+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_CASHTAG_RE = re.compile(r"\$[A-Za-z][A-Za-z0-9]{1,9}")
_TOKEN_RE = re.compile(r'(?i)(?<![A-Za-z])ETH(?![A-Za-z])|\$ETH|Ethereum')

def _snip(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return (s[:SNIP] + "…") if len(s) > SNIP else s

def _dbg(msg):
    if DEBUG:
        log.debug(msg)

def _headers():
    return {"Accept": "application/json", "X-API-Key": TWAPI_API_KEY}

def _extract_id_text(tweet: dict):
    tid = tweet.get("id") or tweet.get("idStr") or tweet.get("tweet_id") or tweet.get("tweetId")
    text = tweet.get("text") or tweet.get("content") or tweet.get("rawContent") or tweet.get("full_text") or ""
    return str(tid) if tid else None, str(text or "")

def _clean_text(s: str) -> str:
    s = _MENTION_RE.sub("", s or "")
    s = _URL_RE.sub("", s)
    return " ".join(s.split())

def _stats_text(raw: str):
    hashtags = _HASHTAG_RE.findall(raw or "")
    mentions = _MENTION_RE.findall(raw or "")
    urls = _URL_RE.findall(raw or "")
    cashtags = [c.upper() for c in _CASHTAG_RE.findall(raw or "")]
    return len(hashtags), len(mentions), len(urls), cashtags

def _is_noise(text: str) -> bool:
    if not text:
        return True
    raw = text
    clean = _clean_text(raw)
    if len(clean) < MIN_TEXT_LEN:
        return True
    h, m, u, cashtags = _stats_text(raw)
    if h > MAX_HASHTAGS or m > MAX_MENTIONS or u > MAX_URLS:
        return True
    if ALLOW_ONLY_ETH_CASHTAG:
        other = [c for c in cashtags if c not in ("$ETH", "$WETH")]
        if len(other) >= 1 and len(cashtags) >= 2:
            return True
    lc = sum(1 for ch in clean if ch.islower())
    uc = sum(1 for ch in clean if ch.isupper())
    letters = lc + uc
    if letters >= 10 and uc / max(1, letters) > MAX_UPPER_RATIO:
        return True
    sym = sum(1 for ch in raw if ch in "!$%^&*~+><=:_|")
    if sym / max(1, len(raw)) > MAX_SYMBOL_RATIO:
        return True
    low = clean.lower()
    for w in _SHILL_WORDS:
        if w in low:
            return True
    return False

def _is_relevant(text: str) -> bool:
    if not REQUIRE_TOKEN_MATCH:
        return True
    return bool(_TOKEN_RE.search(_clean_text(text)))

def _is_reply(tweet: dict) -> bool:
    if tweet.get("is_reply") is True:
        return True
    if tweet.get("in_reply_to_status_id") or tweet.get("in_reply_to_tweet_id"):
        return True
    refs = tweet.get("referenced_tweets") or tweet.get("references") or []
    if isinstance(refs, list):
        for r in refs:
            t = (r.get("type") or "").lower() if isinstance(r, dict) else ""
            if t == "replied_to":
                return True
    return False

def _is_quote(tweet: dict) -> bool:
    if not EXCLUDE_QUOTES:
        return False
    t = (tweet.get("type") or "").lower()
    if t in ("quote", "quoted", "quote_tweet"):
        return True
    return bool(tweet.get("is_quote_status") or tweet.get("quoted_status_id"))

def _normalize(tweet: dict):
    tid = tweet.get("id") or tweet.get("idStr") or tweet.get("tweet_id") or tweet.get("tweetId")
    text = tweet.get("text") or tweet.get("content") or tweet.get("rawContent") or tweet.get("full_text") or ""
    ts = tweet.get("created_at") or tweet.get("date") or tweet.get("timestamp") or tweet.get("time")
    if ts:
        try:
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            else:
                ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            ts = datetime.now(timezone.utc)
    else:
        ts = datetime.now(timezone.utc)
    pm = tweet.get("public_metrics") or tweet.get("metrics") or {}
    likes = pm.get("like_count") or tweet.get("favorite_count") or tweet.get("favoriteCount") or tweet.get("likes") or 0
    rts = pm.get("retweet_count") or tweet.get("retweet_count") or tweet.get("retweetCount") or tweet.get("retweets") or 0
    replies = pm.get("reply_count") or tweet.get("replyCount") or tweet.get("replies") or 0
    return tid, str(text).strip(), ts, int(likes), int(rts), int(replies)

def _fresh_enough(ts: datetime):
    if WINDOW_MIN <= 0:
        return True
    return ts >= datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MIN)

def _build_query():
    q = settings.x_query or '("ETH" OR "Ethereum" OR "$ETH") lang:en'
    if "-is:retweet" not in q and "is:retweet" not in q:
        q += " -is:retweet"
    if "-is:reply" not in q and "is:reply" not in q:
        q += " -is:reply"
    if EXCLUDE_QUOTES and "-is:quote" not in q and "is:quote" not in q:
        q += " -is:quote"
    return q

def _fetch(max_items: int):
    if not TWAPI_API_KEY:
        raise RuntimeError("TWAPI_API_KEY missing")

    want = max(1, min(int(max_items or 10), 100))
    got = []
    pages_left = max(1, PAGES_PER_RUN)
    cursor = ""
    url = f"{TWAPI_BASE}/twitter/tweet/advanced_search"

    with httpx.Client(timeout=httpx.Timeout(10.0, read=20.0)) as client:
        while len(got) < want and pages_left > 0:
            params = {"query": _build_query(), "queryType": "Latest"}
            if cursor:
                params["cursor"] = cursor

            try:
                r = client.get(url, headers=_headers(), params=params)
            except Exception as e:
                _dbg(f"GET {url} error={e}")
                break

            if DEBUG:
                preview = r.text[:300].replace("\n", " ")
                _dbg(f"GET {r.status_code} {r.url} len={len(r.text)} body='{preview}'")

            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    break

                items = []
                if isinstance(data, dict):
                    items = data.get("tweets") or data.get("data") or data.get("items") or data.get("results") or []
                elif isinstance(data, list):
                    items = data

                if not isinstance(items, list) or not items:
                    break

                got.extend(items)
                pages_left -= 1

                if len(got) >= want:
                    break

                has_next = bool(data.get("has_next_page")) if isinstance(data, dict) else False
                next_cursor = str(data.get("next_cursor") or "")

                if pages_left <= 0 or not has_next or not next_cursor:
                    break

                cursor = next_cursor
                time.sleep(max(QPS_SECONDS, 5))
                continue

            if r.status_code in (401, 403):
                raise RuntimeError("Unauthorized to advanced_search")

            if r.status_code == 402:
                # Plan agotado / límite de cuota
                log.info("x_io payment_required 402 -> backoff")
                time.sleep(10)
                break

            if r.status_code == 404:
                log.info("x_io endpoint not found 404")
                time.sleep(2)
                break

            if r.status_code == 429:
                log.info("x_io rate_limited sleep=5s")
                time.sleep(5)
                break

            if 500 <= r.status_code < 600:
                time.sleep(1)
                continue

            # cualquier otro caso
            break

    return got[:want]

def _tweet_permalink(tweet: dict, tid: str) -> str:
    return f"https://x.com/i/web/status/{tid}"



def run_once(max_items: int = None):
    global _last_useful_ts, _backoff
    if max_items is None:
        max_items = MAX_PER_RUN

    try:
        raw = _fetch(max_items)
    except Exception as e:
        log.error(f"twitterapi.io fetch error: {e}")
        return 0

    s = get_session()
    inserted = 0
    useful = False
    seen = 0
    kept = 0
    skip_window = skip_rts = skip_likes = skip_replies = skip_dupe = 0
    skip_irrelevant = skip_reply = skip_quote = skip_noise = skip_llm = 0

    try:
        for t in raw:
            seen += 1
            tid0, text0 = _extract_id_text(t)

            if _is_reply(t):
                skip_reply += 1
                if DETAIL:
                    log.info(f"drop reason=reply id={tid0} text='{_snip(text0)}'")
                continue

            if _is_quote(t):
                skip_quote += 1
                if DETAIL:
                    log.info(f"drop reason=quote id={tid0} text='{_snip(text0)}'")
                continue

            tid, text, ts, likes, rts, replies = _normalize(t)
            if not tid or not text:
                skip_irrelevant += 1
                if DETAIL:
                    log.info(f"drop reason=empty id={tid} likes={likes} rts={rts} replies={replies}")
                continue

            if _is_noise(text):
                skip_noise += 1
                if DETAIL:
                    log.info(f"drop reason=noise id={tid} likes={likes} rts={rts} text='{_snip(text)}'")
                continue

            if not _fresh_enough(ts):
                skip_window += 1
                if DETAIL:
                    log.info(f"drop reason=stale id={tid} ts={ts.isoformat()}")
                continue

            if REQUIRE_TOKEN_MATCH and not _is_relevant(text):
                skip_irrelevant += 1
                if DETAIL:
                    log.info(f"drop reason=no_token_match id={tid} text='{[_snip(text)]}'")
                continue

            if likes < MIN_LIKES:
                skip_likes += 1
                if DETAIL:
                    log.info(f"drop reason=few_likes id={tid} likes={likes} min={MIN_LIKES} text='{_snip(text)}'")
                continue

            if rts < MIN_RTS:
                skip_rts += 1
                if DETAIL:
                    log.info(f"drop reason=few_rts id={tid} rts={rts} min={MIN_RTS} text='{_snip(text)}'")
                continue

            if replies < MIN_REPLIES:
                skip_replies += 1
                if DETAIL:
                    log.info(f"drop reason=few_replies id={tid} replies={replies} min={MIN_REPLIES} text='{_snip(text)}'")
                continue

            # Clasificación LLM opcional
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
                except Exception as e:
                    llm_rel = True
                    llm_conf = 1.0
                    llm_labels = None
                    llm_reason = f"llm_error:{e}"

                if (not llm_rel) or (llm_conf is not None and llm_conf < LLM_MIN_CONF):
                    skip_llm += 1
                    if DETAIL:
                        log.info(f"drop reason=llm id={tid} conf={llm_conf} labels={llm_labels} text='{_snip(text)}'")
                    continue

            uid = hashlib.sha256(str(tid).encode()).hexdigest()
            if s.get(Item, uid):
                skip_dupe += 1
                if DETAIL:
                    log.info(f"drop reason=dupe id={tid}")
                continue

            kept += 1
            score = score_tweet(text)
            s.add(Item(
                id=uid, source="x", asset=settings.asset, ts=ts,
                text=text, score=score, label="tweet",
                llm_relevant=llm_rel, llm_score=llm_conf, llm_labels=llm_labels, llm_reason=llm_reason, url=_tweet_permalink(t, str(tid))
            ))
            inserted += 1
            useful = True

            if DETAIL:
                log.info(f"insert id={tid} likes={likes} rts={rts} score={score:.3f} llm_rel={llm_rel} llm_conf={llm_conf} text='{_snip(text)}'")

            if EMIT_PER_TWEET:
                events.emit("item", f"tweet {tid} inserted", {
                    "id": tid, "likes": likes, "rts": rts, "score": round(score, 3)
                })

        s.commit()
    finally:
        s.close()

    now = time.time()
    if useful:
        _last_useful_ts = now
        _backoff = 0
    else:
        _backoff = min(BACKOFF_MAX, _backoff + max(1, int(settings.poll_seconds / 2)))

    # Log resumen + evento de batch
    log.info(
        f"x_io seen={seen} kept={kept} inserted={inserted} "
        f"skips[reply={skip_reply}, quote={skip_quote}, win={skip_window}, tok={skip_irrelevant}, noise={skip_noise}, "
        f"llm={skip_llm}, likes={skip_likes}, rts={skip_rts}, replies={skip_replies}, dupe={skip_dupe}] "
        f"likes>={MIN_LIKES} rts>={MIN_RTS} replies>={MIN_REPLIES} window_min={WINDOW_MIN} pages_per_run={PAGES_PER_RUN} backoff={_backoff}"
    )

    # Evento de batch (si no hubo inserts, también ayuda a ver actividad)
    events.emit("item", f"{inserted} tweets inserted (batch)", {
        "count": inserted,
        "seen": seen,
        "kept": kept,
        "skips": {
            "reply": skip_reply, "quote": skip_quote, "window": skip_window,
            "token": skip_irrelevant, "noise": skip_noise, "llm": skip_llm,
            "likes": skip_likes, "rts": skip_rts, "replies": skip_replies, "dupe": skip_dupe
        },
        "filters": {
            "min_likes": MIN_LIKES, "min_rts": MIN_RTS, "min_replies": MIN_REPLIES,
            "window_min": WINDOW_MIN
        }
    })

    return inserted

def loop():
    global _backoff
    while True:
        try:
            run_once()
        except Exception as e:
            log.error(f"x_search_io loop error: {e}")
        sleep_for = max(settings.poll_seconds, QPS_SECONDS) + _backoff
        time.sleep(sleep_for)

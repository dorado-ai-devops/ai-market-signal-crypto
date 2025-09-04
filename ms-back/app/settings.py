from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field
from typing import List, Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    telegram_bot_token: Optional[str] = Field(default=None, validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "telegram_bot_token"))
    telegram_chat_id: Optional[str] = Field(default=None, validation_alias=AliasChoices("TELEGRAM_CHAT_ID", "telegram_chat_id"))

    # Ingestores
    rss_feeds: List[str] = Field(default=[
        "https://www.coindesk.com/arc/outboundfeeds/rss/?output=xml",
        "https://cointelegraph.com/rss",
        "https://crypto.news/feed",
        "https://www.newsbtc.com/feed",
        "https://news.bitcoin.com/feed"


    ], validation_alias=AliasChoices("RSS_FEEDS","rss_feeds"))
    x_query: str = Field(default="ETH OR Ethereum OR $ETH", validation_alias=AliasChoices("X_QUERY","x_query"))
    poll_seconds: int = Field(default=60, validation_alias=AliasChoices("POLL_SECONDS","poll_seconds"))
    asset: str = Field(default="ETH-USD", validation_alias=AliasChoices("ASSET","asset"))
    db_path: str = Field(default="/data/market.db", validation_alias=AliasChoices("DB_PATH","db_path"))

    # TwitterAPI.io
    twapi_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("TWAPI_API_KEY","twapi_api_key"))
    twapi_base: str = Field(default="https://api.twitterapi.io", validation_alias=AliasChoices("TWAPI_BASE","twapi_base"))
    twapi_max_per_run: int = Field(default=40, validation_alias=AliasChoices("TWAPI_MAX_PER_RUN","twapi_max_per_run"))
    twapi_min_likes: int = Field(default=0, validation_alias=AliasChoices("TWAPI_MIN_LIKES","twapi_min_likes"))
    twapi_min_rts: int = Field(default=0, validation_alias=AliasChoices("TWAPI_MIN_RTS","twapi_min_rts"))
    twapi_min_replies: int = Field(default=0, validation_alias=AliasChoices("TWAPI_MIN_REPLIES","twapi_min_replies"))
    twapi_window_min: int = Field(default=60, validation_alias=AliasChoices("TWAPI_WINDOW_MIN","twapi_window_min"))
    twapi_backoff_max: int = Field(default=300, validation_alias=AliasChoices("TWAPI_BACKOFF_MAX","twapi_backoff_max"))
    twapi_debug: bool = Field(default=False, validation_alias=AliasChoices("TWAPI_DEBUG","twapi_debug"))

    # LLM
    llm_enabled: bool = Field(default=True, validation_alias=AliasChoices("LLM_ENABLED","llm_enabled"))
    llm_host: str = Field(default="http://127.0.0.1:11434", validation_alias=AliasChoices("LLM_HOST","llm_host"))
    llm_model: str = Field(default="qwen2.5-vl:3b", validation_alias=AliasChoices("LLM_MODEL","llm_model"))
    llm_timeout: int = Field(default=15, validation_alias=AliasChoices("LLM_TIMEOUT","llm_timeout"))
    llm_max_qps: int = Field(default=2, validation_alias=AliasChoices("LLM_MAX_QPS","llm_max_qps"))
    llm_min_conf: float = Field(default=0.6, validation_alias=AliasChoices("LLM_MIN_CONF","llm_min_conf"))

    # Precios / ccxt
    price_exchange: str = Field(default="binance", validation_alias=AliasChoices("PRICE_EXCHANGE","price_exchange"))
    price_symbol: str = Field(default="ETH/USDT", validation_alias=AliasChoices("PRICE_SYMBOL","price_symbol"))
    price_timeframe: str = Field(default="1m", validation_alias=AliasChoices("PRICE_TIMEFRAME","price_timeframe"))
    price_poll_seconds: int = Field(default=30, validation_alias=AliasChoices("PRICE_POLL_SECONDS","price_poll_seconds"))
    price_max_candles_per_pull: int = Field(default=300, validation_alias=AliasChoices("PRICE_MAX_CANDLES_PER_PULL","price_max_candles_per_pull"))

    # Logging
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL","log_level"))

settings = Settings()

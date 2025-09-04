# app/storage.py
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone
from sqlalchemy import text as sql_text
from app.settings import settings
import logging

log = logging.getLogger("ms.db")

engine = create_engine(f"sqlite:///{settings.db_path}", future=True)
Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()

class Item(Base):
    __tablename__ = "items"
    id = Column(String, primary_key=True)
    source = Column(String, index=True)
    asset = Column(String, index=True)
    ts = Column(DateTime, index=True, default=lambda: datetime.now(timezone.utc))
    text = Column(Text)
    score = Column(Float)
    label = Column(String, index=True)
    llm_relevant = Column(Boolean, index=True, default=None)
    llm_score = Column(Float, default=None)
    llm_labels = Column(String, default=None)
    llm_reason = Column(Text, default=None)
    # Nuevos campos de impacto
    impact = Column(Float, default=None)
    impact_meta = Column(Text, default=None)
    url = Column(String, nullable=True)

class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    asset = Column(String, index=True)
    ts = Column(DateTime, index=True, default=lambda: datetime.now(timezone.utc))
    ema15 = Column(Float)
    mentions = Column(Integer)
    action = Column(String, index=True)
    # columnas de precio/indicadores (pueden faltar en DB antigua)
    price_close = Column(Float, nullable=True)
    rsi14 = Column(Float, nullable=True)
    macd = Column(Float, nullable=True)
    macd_signal = Column(Float, nullable=True)
    atr_pct = Column(Float, nullable=True)
    price_bias = Column(String, nullable=True)

class Price(Base):
    __tablename__ = "prices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    timeframe = Column(String, index=True)
    ts = Column(DateTime, index=True)
    o = Column(Float)
    h = Column(Float)
    l = Column(Float)
    c = Column(Float)
    v = Column(Float)

def _ensure_prices_migration(conn):
    # Crea la tabla si no existe
    conn.execute(sql_text("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR,
            timeframe VARCHAR,
            ts DATETIME,
            o FLOAT,
            h FLOAT,
            l FLOAT,
            c FLOAT,
            v FLOAT
        )
    """))

    # Lee columnas actuales
    result = conn.execute(sql_text("PRAGMA table_info(prices)"))
    cols = {row[1] for row in result.fetchall()}

    # Añade columnas que falten (migración suave)
    alters = []
    if "symbol" not in cols:
        alters.append("ALTER TABLE prices ADD COLUMN symbol VARCHAR")
    if "timeframe" not in cols:
        alters.append("ALTER TABLE prices ADD COLUMN timeframe VARCHAR")
    if "ts" not in cols:
        alters.append("ALTER TABLE prices ADD COLUMN ts DATETIME")
    if "o" not in cols:
        alters.append("ALTER TABLE prices ADD COLUMN o FLOAT")
    if "h" not in cols:
        alters.append("ALTER TABLE prices ADD COLUMN h FLOAT")
    if "l" not in cols:
        alters.append("ALTER TABLE prices ADD COLUMN l FLOAT")
    if "c" not in cols:
        alters.append("ALTER TABLE prices ADD COLUMN c FLOAT")
    if "v" not in cols:
        alters.append("ALTER TABLE prices ADD COLUMN v FLOAT")

    for stmt in alters:
        conn.execute(sql_text(stmt))
        log.info("migrated prices: %s", stmt)

    # Rellena timeframe/symbol por defecto si quedaron NULL en filas antiguas
    conn.execute(sql_text("""
        UPDATE prices
        SET timeframe = COALESCE(timeframe, :tf)
        WHERE timeframe IS NULL
    """), {"tf": settings.price_timeframe})
    conn.execute(sql_text("""
        UPDATE prices
        SET symbol = COALESCE(symbol, :sym)
        WHERE symbol IS NULL
    """), {"sym": settings.price_symbol})

    # Crea índices si no existen (SQLite permite IF NOT EXISTS)
    conn.execute(sql_text("""
        CREATE INDEX IF NOT EXISTS ix_prices_symbol ON prices(symbol)
    """))
    conn.execute(sql_text("""
        CREATE INDEX IF NOT EXISTS ix_prices_timeframe ON prices(timeframe)
    """))
    conn.execute(sql_text("""
        CREATE INDEX IF NOT EXISTS ix_prices_ts ON prices(ts)
    """))
    # Índice compuesto para acelerar queries por (symbol,timeframe,ts)
    conn.execute(sql_text("""
        CREATE INDEX IF NOT EXISTS ix_prices_key ON prices(symbol, timeframe, ts)
    """))

def init_db():
    # Crea tablas declaradas si no existen
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        # items -> columnas LLM (compatibilidad) + impacto
        result = conn.execute(sql_text("PRAGMA table_info(items)"))
        cols = {row[1] for row in result.fetchall()}
        alters = []
        if "url" not in cols:
            alters.append('ALTER TABLE items ADD COLUMN url VARCHAR')
        if "llm_relevant" not in cols:
            alters.append('ALTER TABLE items ADD COLUMN llm_relevant BOOLEAN')
        if "llm_score" not in cols:
            alters.append('ALTER TABLE items ADD COLUMN llm_score FLOAT')
        if "llm_labels" not in cols:
            alters.append('ALTER TABLE items ADD COLUMN llm_labels VARCHAR')
        if "llm_reason" not in cols:
            alters.append('ALTER TABLE items ADD COLUMN llm_reason TEXT')
        if "impact" not in cols:
            alters.append('ALTER TABLE items ADD COLUMN impact FLOAT')
        if "impact_meta" not in cols:
            alters.append('ALTER TABLE items ADD COLUMN impact_meta TEXT')
        for stmt in alters:
            conn.execute(sql_text(stmt))
            log.info("migrated items: %s", stmt)

        # signals -> columnas de precio si faltan
        result = conn.execute(sql_text("PRAGMA table_info(signals)"))
        scols = {row[1] for row in result.fetchall()}
        salters = []
        if "price_close" not in scols:
            salters.append('ALTER TABLE signals ADD COLUMN price_close FLOAT')
        if "rsi14" not in scols:
            salters.append('ALTER TABLE signals ADD COLUMN rsi14 FLOAT')
        if "macd" not in scols:
            salters.append('ALTER TABLE signals ADD COLUMN macd FLOAT')
        if "macd_signal" not in scols:
            salters.append('ALTER TABLE signals ADD COLUMN macd_signal FLOAT')
        if "atr_pct" not in scols:
            salters.append('ALTER TABLE signals ADD COLUMN atr_pct FLOAT')
        if "price_bias" not in scols:
            salters.append('ALTER TABLE signals ADD COLUMN price_bias VARCHAR')
        for stmt in salters:
            conn.execute(sql_text(stmt))
            log.info("migrated signals: %s", stmt)

        # prices -> migración fuerte (añade columnas que falten + índices)
        _ensure_prices_migration(conn)

def get_session():
    return Session()

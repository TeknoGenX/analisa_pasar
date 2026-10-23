# data_ingestion/iqoption/service.py
"""
Layanan Sinkronisasi Data IQ Option ke Basis Data Django SQLite3 & Redis Cache.
Menyimpan riwayat candle ke model MarketData menggunakan bulk upsert berkecepatan tinggi.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from django.core.cache import cache
from django.utils import timezone as django_timezone

from data_ingestion.models import MarketData, MarketInstrument
from .client import IQOptionClient
from .constants import POPULAR_IQOPTION_INSTRUMENTS, resolve_active_id

logger = logging.getLogger(__name__)

# --- Konstanta Pemetaan ---
CRYPTO_KEYWORDS = ('BTC', 'ETH', 'LTC', 'XRP', 'DASH', 'EOS', 'TRX', 'CRYPTO')
COMMODITY_KEYWORDS = ('XAU', 'GOLD', 'XAG', 'SILVER', 'OIL', 'BRENT', 'WTI')
STOCK_KEYWORDS = ('AAPL', 'APPLE', 'TSLA', 'TESLA', 'GOOG', 'AMZN', 'MSFT', 'FB', 'META')
COMMODITY_SYMBOL_MAP = {'XAUUSD': 'GC=F', 'XAGUSD': 'SI=F'}


# --- Fungsi Bantuan Internal ---
def determine_category(symbol_name: str) -> str:
    """Menentukan kategori instrumen berdasarkan nama simbol."""
    s = symbol_name.upper()
    if any(c in s for c in CRYPTO_KEYWORDS):
        return 'CRYPTO'
    if any(comm in s for comm in COMMODITY_KEYWORDS):
        return 'COMMODITY'
    if any(stk in s for stk in STOCK_KEYWORDS):
        return 'STOCK'
    return 'FOREX'


def _parse_candle_timestamp(candle: Dict[str, Any]) -> datetime:
    """Mengekstrak dan memastikan timestamp candle memiliki informasi zona waktu."""
    ts = candle.get('timestamp')
    if not ts:
        from_ts = candle.get('from', 0)
        ts = datetime.fromtimestamp(from_ts, tz=timezone.utc)

    if django_timezone.is_naive(ts):
        ts = django_timezone.make_aware(ts)

    return ts


def _clear_instrument_cache(instrument: MarketInstrument, timeframe: str) -> None:
    """Menghapus kunci cache dashboard yang relevan secara aman."""
    cache_keys = [
        f'dashboard_detail_{instrument.symbol}_{timeframe}',
        f'dashboard_detail_{instrument.symbol}_{timeframe}_IQOPTION',
        f'dashboard_market_data_{timeframe}',
        f'dashboard_market_data_{timeframe}_all',
        f'dashboard_market_data_{timeframe}_{instrument.market_category}',
    ]
    try:
        cache.delete_many(cache_keys)
    except Exception as cache_err:
        logger.debug(f"Pembersihan cache dilewati ({instrument.symbol}): {cache_err}")


# --- Layanan Utama ---
def get_or_create_iqoption_instrument(
    symbol_query: str, 
    category: Optional[str] = None
) -> MarketInstrument:
    """
    Mencari atau membuat MarketInstrument yang sesuai dengan aset IQ Option.
    Menghubungkan simbol standar ('EURUSD') ke instrumen yang sudah ada ('EURUSD=X')
    atau membuat entri baru untuk aset khusus (seperti 'EURUSD-OTC').
    """
    sq = str(symbol_query).strip()
    name, _ = resolve_active_id(sq)
    target_symbol = name or sq.upper()

    if not target_symbol.endswith('-OTC'):
        eq_forex = MarketInstrument.objects.filter(symbol__iexact=f"{target_symbol}=X").first()
        if eq_forex:
            return eq_forex

        if target_symbol.endswith('USD') and len(target_symbol) > 3:
            base_crypto = target_symbol[:-3]
            eq_crypto = MarketInstrument.objects.filter(symbol__iexact=f"{base_crypto}-USD").first()
            if eq_crypto:
                return eq_crypto

        if target_symbol in COMMODITY_SYMBOL_MAP:
            eq_comm = MarketInstrument.objects.filter(symbol__iexact=COMMODITY_SYMBOL_MAP[target_symbol]).first()
            if eq_comm:
                return eq_comm

    inst = MarketInstrument.objects.filter(symbol__iexact=target_symbol).first()
    if inst:
        return inst

    cat = category or determine_category(target_symbol)
    friendly_name = f"{target_symbol} (IQ Option)"
    for pop in POPULAR_IQOPTION_INSTRUMENTS:
        if pop['symbol'].upper() == target_symbol.upper():
            friendly_name = pop['name']
            cat = pop.get('category', cat)
            break

    data_src = 'IQOPTION' if target_symbol.endswith('-OTC') else 'YAHOO'

    inst = MarketInstrument.objects.create(
        symbol=target_symbol,
        name=friendly_name,
        market_category=cat,
        data_source=data_src,
        is_active=True
    )
    logger.info(f"Instrumen IQ Option baru dibuat di DB: {inst.symbol} ({inst.name}) [{inst.market_category}] [{data_src}]")
    return inst


def save_candles_to_market_data(
    instrument: MarketInstrument, 
    timeframe: str, 
    candles: List[Dict[str, Any]]
) -> int:
    """
    Menyimpan daftar lilin hasil unduhan IQ Option ke SQLite3 secara massal (bulk upsert).
    """
    if not candles:
        return 0

    records_to_upsert = []
    seen_timestamps = set()

    for c in candles:
        ts = _parse_candle_timestamp(c)

        if ts in seen_timestamps:
            continue
        seen_timestamps.add(ts)

        records_to_upsert.append(
            MarketData(
                instrument=instrument,
                timeframe=timeframe,
                data_source='IQOPTION',
                timestamp=ts,
                open_price=float(c['open']),
                high_price=float(c.get('high', c.get('max', c['open']))),
                low_price=float(c.get('low', c.get('min', c['open']))),
                close_price=float(c['close']),
                volume=float(c.get('volume', 0.0)),
            )
        )

    if records_to_upsert:
        MarketData.objects.bulk_create(
            records_to_upsert,
            batch_size=1000,
            update_conflicts=True,
            update_fields=['open_price', 'high_price', 'low_price', 'close_price', 'volume'],
            unique_fields=['instrument', 'timeframe', 'data_source', 'timestamp']
        )
        _clear_instrument_cache(instrument, timeframe)

    return len(records_to_upsert)


def sync_iqoption_candles(
    symbol: str,
    timeframe: str = '1m',
    count: int = 200,
    end_time: Optional[Any] = None,
    ssid: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    demo_feed: bool = False
) -> Dict[str, Any]:
    """
    Fungsi all-in-one untuk menarik riwayat candle dari IQ Option Traderoom
    dan menyimpannya langsung ke database.
    """
    inst = get_or_create_iqoption_instrument(symbol)
    client = IQOptionClient(ssid=ssid, email=email, password=password, demo_feed=demo_feed)

    try:
        candles = client.get_candles(
            active_id_or_name=inst.symbol,
            timeframe=timeframe,
            count=count,
            end_time=end_time
        )
        saved = save_candles_to_market_data(inst, timeframe, candles)
        return {
            'success': True,
            'instrument': inst.symbol,
            'timeframe': timeframe,
            'records_saved': saved,
            'message': f"Berhasil menyimpan {saved} bar data candle untuk {inst.symbol} [{timeframe}]."
        }
    except Exception as e:
        logger.error(f"Gagal menyinkronkan data IQ Option untuk {inst.symbol}: {e}")
        return {
            'success': False,
            'instrument': inst.symbol,
            'timeframe': timeframe,
            'records_saved': 0,
            'error': str(e)
        }
"""
Layanan Sinkronisasi Data IQ Option ke Basis Data Django SQLite3 & Redis Cache.
Menyimpan riwayat candle ke model MarketData menggunakan bulk upsert berkecepatan tinggi.
"""

import logging
from datetime import datetime, timezone
from django.core.cache import cache
from data_ingestion.models import MarketInstrument, MarketData
from .constants import (
    ACTIVES,
    ACTIVES_REVERSE,
    TIMEFRAME_TO_SECONDS,
    POPULAR_IQOPTION_INSTRUMENTS,
    resolve_active_id,
)
from .client import IQOptionClient

logger = logging.getLogger(__name__)


def determine_category(symbol_name):
    """Menentukan kategori instrumen berdasarkan nama simbol"""
    s = symbol_name.upper()
    if any(c in s for c in ['BTC', 'ETH', 'LTC', 'XRP', 'DASH', 'EOS', 'TRX', 'CRYPTO']):
        return 'CRYPTO'
    elif any(comm in s for comm in ['XAU', 'GOLD', 'XAG', 'SILVER', 'OIL', 'BRENT', 'WTI']):
        return 'COMMODITY'
    elif any(stk in s for stk in ['AAPL', 'APPLE', 'TSLA', 'TESLA', 'GOOG', 'AMZN', 'MSFT', 'FB', 'META']):
        return 'STOCK'
    return 'FOREX'


def get_or_create_iqoption_instrument(symbol_query, category=None):
    """
    Mencari atau membuat MarketInstrument yang sesuai dengan aset IQ Option.
    Menghubungkan simbol standar ('EURUSD') ke instrumen yang sudah ada ('EURUSD=X')
    atau membuat entri baru untuk aset khusus (seperti 'EURUSD-OTC').
    """
    sq = str(symbol_query).strip()
    name, active_id = resolve_active_id(sq)
    target_symbol = name or sq.upper()

    # 1. Jika bukan OTC, cek apakah ada pasangan yfinance yang ekuivalen di database
    if not target_symbol.endswith('-OTC'):
        # 1a. Cek Forex (EURUSD -> EURUSD=X)
        eq_forex = MarketInstrument.objects.filter(symbol__iexact=f"{target_symbol}=X").first()
        if eq_forex:
            return eq_forex

        # 1b. Cek Kripto (BTCUSD -> BTC-USD)
        if target_symbol.endswith('USD') and len(target_symbol) > 3:
            base_crypto = target_symbol[:-3]
            eq_crypto = MarketInstrument.objects.filter(symbol__iexact=f"{base_crypto}-USD").first()
            if eq_crypto:
                return eq_crypto

        # 1c. Cek Komoditas (XAUUSD -> GC=F, XAGUSD -> SI=F)
        comm_map = {'XAUUSD': 'GC=F', 'XAGUSD': 'SI=F'}
        if target_symbol in comm_map:
            eq_comm = MarketInstrument.objects.filter(symbol__iexact=comm_map[target_symbol]).first()
            if eq_comm:
                return eq_comm

    # 2. Cek kecocokan langsung di database (misal: EURUSD-OTC)
    inst = MarketInstrument.objects.filter(symbol__iexact=target_symbol).first()
    if inst:
        return inst

    # 3. Buat instrumen baru jika belum ada di database (khusus OTC atau aset baru)
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


def save_candles_to_market_data(instrument, timeframe, candles):
    """
    Menyimpan daftar lilin hasil unduhan IQ Option ke SQLite3 secara massal (bulk upsert).
    """
    if not candles:
        return 0

    records_to_upsert = []
    seen_timestamps = set()

    for c in candles:
        ts = c.get('timestamp')
        if not ts:
            from_ts = c.get('from', 0)
            ts = datetime.fromtimestamp(from_ts, tz=timezone.utc)

        if ts in seen_timestamps:
            continue
        seen_timestamps.add(ts)

        records_to_upsert.append(MarketData(
            instrument=instrument,
            timeframe=timeframe,
            timestamp=ts,
            open_price=float(c['open']),
            high_price=float(c.get('high', c.get('max', c['open']))),
            low_price=float(c.get('low', c.get('min', c['open']))),
            close_price=float(c['close']),
            volume=float(c.get('volume', 0.0)),
        ))

    if records_to_upsert:
        MarketData.objects.bulk_create(
            records_to_upsert,
            batch_size=1000,
            update_conflicts=True,
            update_fields=['open_price', 'high_price', 'low_price', 'close_price', 'volume'],
            unique_fields=['instrument', 'timeframe', 'timestamp']
        )

        # Bersihkan cache terkait instrumen dan timeframe ini secara aman
        try:
            cache.delete(f'dashboard_detail_{instrument.symbol}_{timeframe}')
            cache.delete(f'dashboard_market_data_{timeframe}')
            cache.delete(f'dashboard_market_data_{timeframe}_all')
            cache.delete(f'dashboard_market_data_{timeframe}_{instrument.market_category}')
        except Exception as cache_err:
            logger.debug(f"Pembersihan cache dilewati ({instrument.symbol}): {cache_err}")

    return len(records_to_upsert)


def sync_iqoption_candles(
    symbol,
    timeframe='1m',
    count=200,
    end_time=None,
    ssid=None,
    email=None,
    password=None,
    demo_feed=False
):
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

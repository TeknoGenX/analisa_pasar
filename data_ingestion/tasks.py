import logging
import pandas as pd
import yfinance as yf
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from .models import MarketInstrument, MarketData

logger = logging.getLogger('data_ingestion')

# Konfigurasi periode unduh optimal berdasarkan interval yfinance
TIMEFRAME_CONFIG = {
    '1m': {'period': '2d', 'interval': '1m'},
    '5m': {'period': '5d', 'interval': '5m'},
    '15m': {'period': '15d', 'interval': '15m'},
    '30m': {'period': '30d', 'interval': '30m'},
    '1h': {'period': '60d', 'interval': '1h'},
    '1d': {'period': '60d', 'interval': '1d'},
    '1wk': {'period': '1y', 'interval': '1wk'},
    '1mo': {'period': '2y', 'interval': '1mo'},
}


def extract_ticker_df(data, symbol):
    """
    Mengekstrak DataFrame satu instrumen dari hasil yfinance.download
    secara aman terhadap perubahan struktur MultiIndex.
    """
    if data is None or data.empty:
        return None
    try:
        df = data.copy()
        if isinstance(df.columns, pd.MultiIndex):
            if symbol in df.columns.levels[0]:
                df = df[symbol].copy()
            elif len(df.columns.levels) > 1 and symbol in df.columns.levels[1]:
                df = df.xs(symbol, level=1, axis=1).copy()
            else:
                matched_level = [lvl for lvl in df.columns.levels[0] if symbol in str(lvl)]
                if matched_level:
                    df = df[matched_level[0]].copy()
                else:
                    return None
        
        if df is None or df.empty:
            return None

        # Standarisasi nama kolom menjadi kapital
        df.columns = [str(c).capitalize() for c in df.columns]
        df = df.dropna(how='all')
        if 'Close' in df.columns:
            df = df.dropna(subset=['Close'])

        return df
    except Exception as e:
        # Penanganan senyap untuk menghindari log berlebih pada simbol yang tidak didukung
        return None


@shared_task
def fetch_market_prices(timeframe='1d', symbols=None):
    """
    Menarik data riwayat pasar secara incremental (hanya data baru yang belum ada di SQLite3)
    untuk mempercepat proses dan mencegah duplikasi data candle.
    """
    if timeframe not in TIMEFRAME_CONFIG:
        timeframe = '1d'

    cfg = TIMEFRAME_CONFIG[timeframe]
    period = cfg['period']
    interval = cfg['interval']

    if symbols:
        instruments = list(MarketInstrument.objects.filter(is_active=True, symbol__in=symbols))
    else:
        instruments = list(MarketInstrument.objects.filter(is_active=True))

    if not instruments:
        logger.info("Tidak ada instrumen aktif yang ditemukan.")
        return "No active instruments."

    total_symbols = len(instruments)
    logger.info(
        f"Mulai menarik data yfinance (Incremental) timeframe='{timeframe}' "
        f"untuk {total_symbols} instrumen aktif."
    )

    batch_size = 15
    success_count = 0
    total_records_saved = 0

    for i in range(0, total_symbols, batch_size):
        batch = instruments[i:i + batch_size]
        batch_symbols = [inst.symbol for inst in batch]

        # 1. Optimasi Periode Unduh: Jika semua instrumen dalam batch sudah memiliki data, 
        # cukup tarik periode pendek (misal 1d) untuk mencakup data terbaru.
        dynamic_period = period
        if timeframe in ['1m', '5m']:
            existing_count = MarketInstrument.objects.filter(
                id__in=[inst.id for inst in batch],
                price_data__timeframe=timeframe
            ).distinct().count()
            if existing_count == len(batch):
                dynamic_period = '1d'  # Hanya ambil 1 hari terakhir jika semua instrumen sudah punya data

        try:
            # Menggunakan suppress/silent error untuk batch yang memiliki simbol tidak valid/delisted
            data = yf.download(
                tickers=batch_symbols,
                period=dynamic_period,
                interval=interval,
                group_by='ticker',
                threads=True,
                progress=False,
                auto_adjust=True
            )
        except Exception:
            # Lewati batch secara aman tanpa memunculkan traceback error merah di terminal
            continue

        if data is None or data.empty:
            continue

        records_to_upsert = []
        seen_keys = set()

        for inst in batch:
            try:
                # 2. Ambil timestamp terakhir yang sudah tersimpan di SQLite3 untuk instrumen ini
                last_record = MarketData.objects.filter(instrument=inst, timeframe=timeframe).order_by('-timestamp').first()
                last_timestamp = last_record.timestamp if last_record else None

                ticker_data = extract_ticker_df(data, inst.symbol)
                if ticker_data is None or ticker_data.empty:
                    continue

                for raw_time, row in ticker_data.iterrows():
                    close_val = row.get('Close')
                    if pd.isna(close_val) or close_val is None:
                        continue

                    # Pastikan timestamp berzona waktu (aware)
                    if timezone.is_naive(raw_time):
                        aware_time = timezone.make_aware(raw_time)
                    else:
                        aware_time = raw_time

                    # 3. INCREMENTAL FILTER: Lewati data jika waktu STRICTLY lebih lama dari timestamp terakhir.
                    # Jika aware_time == last_timestamp, biarkan masuk agar nilai final penutupan candle ter-update via update_conflicts.
                    if last_timestamp and aware_time < last_timestamp:
                        continue

                    key = (inst.id, aware_time)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    vol_val = row.get('Volume', 0)
                    volume_clean = 0.0 if (pd.isna(vol_val) or vol_val is None) else float(vol_val)

                    records_to_upsert.append(MarketData(
                        instrument=inst,
                        timeframe=timeframe,
                        timestamp=aware_time,
                        open_price=float(row['Open']) if pd.notna(row.get('Open')) else float(close_val),
                        high_price=float(row['High']) if pd.notna(row.get('High')) else float(close_val),
                        low_price=float(row['Low']) if pd.notna(row.get('Low')) else float(close_val),
                        close_price=float(close_val),
                        volume=volume_clean
                    ))

                success_count += 1
            except Exception:
                pass

        if records_to_upsert:
            try:
                MarketData.objects.bulk_create(
                    records_to_upsert,
                    batch_size=1000,
                    update_conflicts=True,
                    update_fields=['open_price', 'high_price', 'low_price', 'close_price', 'volume'],
                    unique_fields=['instrument', 'timeframe', 'timestamp']
                )
                total_records_saved += len(records_to_upsert)
            except Exception as e:
                logger.error(f"Gagal bulk_create database untuk batch {batch_symbols} [{timeframe}]: {str(e)}")

    # Bersihkan cache dashboard untuk timeframe ini agar tampilan langsung terbarui
    cache.delete(f'dashboard_market_data_{timeframe}')
    for cat in ['all', 'FOREX', 'CRYPTO', 'STOCK', 'COMMODITY']:
        cache.delete(f'dashboard_market_data_{timeframe}_{cat}')
    if symbols:
        for sym in symbols:
            cache.delete(f'dashboard_detail_{sym}_{timeframe}')

    result_msg = (
        f"Selesai Incremental [{timeframe}]: {success_count}/{total_symbols} instrumen diproses. "
        f"Total {total_records_saved} bar data candle baru tersimpan ke SQLite3."
    )
    logger.info(result_msg)
    return result_msg


@shared_task
def fetch_all_active_timeframes(timeframes=None):
    """
    Menjalankan penarikan data secara berurutan untuk seluruh timeframe
    (default: '1m', '5m', '15m', '30m', '1h', '1d', '1wk').
    """
    if timeframes is None:
        timeframes = ['1m', '5m', '15m', '30m', '1h', '1d', '1wk']

    results = {}
    for tf in timeframes:
        results[tf] = fetch_market_prices(timeframe=tf)
    return results
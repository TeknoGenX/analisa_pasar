# trading_dashboard/views.py
import csv
import json
import logging
from urllib.parse import urlencode
from collections.abc import Hashable
from typing import Any, cast

import pandas as pd
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.core.cache import cache
from data_ingestion.models import MarketInstrument, MarketData
from technical_indicators.services import analyze_instrument_optimized, get_detailed_prediction

logger = logging.getLogger(__name__)


def typed_analyze_instrument_optimized(
    instrument_id: int, timeframe: str = '1d', data_source: str | None = None
) -> dict[Hashable, Any] | None:
    """Type-safe wrapper around the imported analysis function."""
    return cast(
        dict[Hashable, Any] | None,
        analyze_instrument_optimized(
            instrument_id, timeframe=timeframe, data_source=data_source
        ),
    )


def typed_get_detailed_prediction(
    instrument_id: int, timeframe: str = '1d', data_source: str | None = None
) -> dict[str, Any] | None:
    """Type-safe wrapper around the imported detailed prediction function."""
    return cast(
        dict[str, Any] | None,
        get_detailed_prediction(
            instrument_id, timeframe=timeframe, data_source=data_source
        ),
    )

TIMEFRAME_LIST = [
    ('1m', '1 Menit'),
    ('5m', '5 Menit'),
    ('15m', '15 Menit'),
    ('30m', '30 Menit'),
    ('1h', '1 Jam'),
    ('1d', '1 Hari'),
    ('1wk', '1 Minggu'),
    ('1mo', '1 Bulan'),
]
VALID_TIMEFRAMES = dict(TIMEFRAME_LIST)

POPULAR_SYMBOLS = [
    ('EURUSD=X', 'EUR/USD', 'FOREX'),
    ('EURUSD-OTC', 'EUR/USD (OTC IQ)', 'FOREX'),
    ('GBPUSD=X', 'GBP/USD', 'FOREX'),
    ('USDJPY=X', 'USD/JPY', 'FOREX'),
    ('BTC-USD', 'BTC/USD', 'CRYPTO'),
    ('ETH-USD', 'ETH/USD', 'CRYPTO'),
    ('BBCA.JK', 'BBCA', 'STOCK'),
    ('GC=F', 'Emas (Gold)', 'COMMODITY'),
    ('CL=F', 'Minyak (WTI)', 'COMMODITY'),
]


def safe_round(val, decimals=4):
    """Membantu pembulatan angka secara aman dari nilai NaN atau None"""
    if val is None or pd.isna(val):
        return None
    try:
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return None


def resolve_instrument(symbol_query):
    """
    Pencari instrumen cerdas dan fleksibel:
    Mendukung simbol lengkap ('EURUSD=X'), tanpa akhiran ('EURUSD'),
    simbol OTC IQ Option ('EURUSD-OTC'), huruf kecil/besar, nama parsial, atau ID numerik.
    """
    if not symbol_query or str(symbol_query).strip().lower() in ['', 'all', 'semua']:
        return None

    sq = str(symbol_query).strip()

    # 1. Cek kecocokan simbol persis (case insensitive)
    inst = MarketInstrument.objects.filter(symbol__iexact=sq).first()
    if inst:
        return inst

    # 1b. Cek normalisasi OTC (contoh: EURUSD_OTC -> EURUSD-OTC)
    if '_' in sq and 'otc' in sq.lower():
        inst = MarketInstrument.objects.filter(symbol__iexact=sq.replace('_', '-')).first()
        if inst:
            return inst

    # 2. Cek tambahan sufiks Forex '=X' (contoh: EURUSD -> EURUSD=X)
    inst = MarketInstrument.objects.filter(symbol__iexact=f"{sq}=X").first()
    if inst:
        return inst

    # 3. Cek tambahan sufiks Kripto '-USD' (contoh: BTC -> BTC-USD)
    inst = MarketInstrument.objects.filter(symbol__iexact=f"{sq}-USD").first()
    if inst:
        return inst

    # 3b. Cek kripto dengan sufiks USD tanpa strip (contoh: BTCUSD -> BTC-USD)
    if sq.upper().endswith('USD') and len(sq) > 3:
        base = sq[:-3].upper()
        inst = MarketInstrument.objects.filter(symbol__iexact=f"{base}-USD").first()
        if inst:
            return inst

    # 3c. Cek komoditas populer (contoh: XAUUSD / GOLD -> GC=F, XAGUSD / SILVER -> SI=F)
    comm_map = {'XAUUSD': 'GC=F', 'GOLD': 'GC=F', 'XAGUSD': 'SI=F', 'SILVER': 'SI=F'}
    if sq.upper() in comm_map:
        inst = MarketInstrument.objects.filter(symbol__iexact=comm_map[sq.upper()]).first()
        if inst:
            return inst

    # 4. Cek tambahan sufiks Saham IDX '.JK' (contoh: BBCA -> BBCA.JK)
    inst = MarketInstrument.objects.filter(symbol__iexact=f"{sq}.JK").first()
    if inst:
        return inst

    # 5. Cek jika query berupa ID numerik
    if sq.isdigit():
        inst = MarketInstrument.objects.filter(id=int(sq)).first()
        if inst:
            return inst

    # 6. Cek kecocokan parsial pada simbol
    inst = MarketInstrument.objects.filter(symbol__icontains=sq).first()
    if inst:
        return inst

    # 7. Cek kecocokan parsial pada nama aset (contoh: 'Euro', 'Bitcoin', 'Gold')
    inst = MarketInstrument.objects.filter(name__icontains=sq).first()
    if inst:
        return inst

    return None


def get_instruments_grouped():
    """Mengambil daftar seluruh instrumen aktif yang dikelompokkan berdasarkan kategori"""
    instruments = MarketInstrument.objects.filter(is_active=True).order_by('market_category', 'symbol')
    grouped = {}
    for inst in instruments:
        cat = inst.get_market_category_display()
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append({
            'id': inst.id,
            'symbol': inst.symbol,
            'name': inst.name,
            'category': inst.market_category,
        })
    return grouped


def compute_summary(items):
    """Menghitung ringkasan sentimen pasar dinamis dari hasil kalkulasi seluruh instrumen"""
    if not items:
        return {
            'market_sentiment': 'TIDAK ADA DATA',
            'market_badge_class': 'bg-secondary',
            'tech_status': 'Belum Ada Data',
            'tech_badge_class': 'bg-secondary bg-opacity-10 text-secondary',
            'ma_status': 'Belum Ada Data',
            'ma_badge_class': 'bg-secondary bg-opacity-10 text-secondary',
        }

    buy_count = sum(1 for x in items if 'BUY' in x.get('signal', ''))
    sell_count = sum(1 for x in items if 'SELL' in x.get('signal', ''))
    has_strong_buy = any(x.get('signal') == 'STRONG BUY' for x in items)
    has_strong_sell = any(x.get('signal') == 'STRONG SELL' for x in items)

    if buy_count > sell_count:
        if has_strong_buy:
            sentiment = 'BELI KUAT'
            badge_cls = 'bg-success'
            tech_status = 'Beli Kuat / Bullish'
            ma_status = 'Tren Naik Kuat'
        else:
            sentiment = 'BELI'
            badge_cls = 'bg-success bg-opacity-75'
            tech_status = 'Beli / Bullish'
            ma_status = 'Tren Naik'
        tech_badge = 'bg-success bg-opacity-10 text-success'
        ma_badge = 'bg-success bg-opacity-10 text-success'
    elif sell_count > buy_count:
        if has_strong_sell:
            sentiment = 'JUAL KUAT'
            badge_cls = 'bg-danger'
            tech_status = 'Jual Kuat / Bearish'
            ma_status = 'Tren Turun Kuat'
        else:
            sentiment = 'JUAL'
            badge_cls = 'bg-danger bg-opacity-75'
            tech_status = 'Jual / Bearish'
            ma_status = 'Tren Turun'
        tech_badge = 'bg-danger bg-opacity-10 text-danger'
        ma_badge = 'bg-danger bg-opacity-10 text-danger'
    else:
        sentiment = 'NETRAL / TAHAN'
        badge_cls = 'bg-warning text-dark'
        tech_status = 'Netral / Konsolidasi'
        tech_badge = 'bg-warning bg-opacity-10 text-dark'
        ma_status = 'Konsolidasi'
        ma_badge = 'bg-secondary bg-opacity-10 text-secondary'

    return {
        'market_sentiment': sentiment,
        'market_badge_class': badge_cls,
        'tech_status': tech_status,
        'tech_badge_class': tech_badge,
        'ma_status': ma_status,
        'ma_badge_class': ma_badge,
    }


def compute_single_instrument_summary(prediction_data):
    """Menghasilkan kartu ringkasan sentimen khusus untuk 1 instrumen yang sedang dipilih"""
    if not prediction_data or not prediction_data.get('has_enough_data'):
        return {
            'market_sentiment': 'DATA TERBATAS',
            'market_badge_class': 'bg-secondary',
            'tech_status': 'Perlu Sinkronisasi Data',
            'tech_badge_class': 'bg-secondary bg-opacity-10 text-secondary',
            'ma_status': 'Belum Cukup Candle',
            'ma_badge_class': 'bg-secondary bg-opacity-10 text-secondary',
        }

    pred = prediction_data.get('prediction', {})
    ind = prediction_data.get('indicators', {})
    direction = pred.get('direction', 'KONSOLIDASI')
    prob_up = pred.get('prob_up', 50)
    prob_down = pred.get('prob_down', 50)

    if direction == 'NAIK':
        sentiment = f"PREDIKSI: NAIK ({prob_up}%)"
        badge_cls = 'bg-success'
        tech_status = f"Peluang BUY ({ind.get('rsi_status', 'Bullish')})"
        tech_badge = 'bg-success bg-opacity-10 text-success'
        ma_status = 'Golden Cross / Tren Naik'
        ma_badge = 'bg-success bg-opacity-10 text-success'
    elif direction == 'TURUN':
        sentiment = f"PREDIKSI: TURUN ({prob_down}%)"
        badge_cls = 'bg-danger'
        tech_status = f"Peluang SELL ({ind.get('rsi_status', 'Bearish')})"
        tech_badge = 'bg-danger bg-opacity-10 text-danger'
        ma_status = 'Death Cross / Tren Turun'
        ma_badge = 'bg-danger bg-opacity-10 text-danger'
    else:
        sentiment = "PREDIKSI: KONSOLIDASI"
        badge_cls = 'bg-warning text-dark'
        tech_status = "Sideways / Menunggu Sinyal"
        tech_badge = 'bg-warning bg-opacity-10 text-dark'
        ma_status = "Konsolidasi di Sekitar EMA"
        ma_badge = 'bg-secondary bg-opacity-10 text-secondary'

    return {
        'market_sentiment': sentiment,
        'market_badge_class': badge_cls,
        'tech_status': tech_status,
        'tech_badge_class': tech_badge,
        'ma_status': ma_status,
        'ma_badge_class': ma_badge,
    }


def main_dashboard(request):
    tf = request.GET.get('tf', '1d')
    if tf not in VALID_TIMEFRAMES:
        tf = '1d'

    symbol_query = request.GET.get('symbol', '').strip()
    category_filter = request.GET.get('category', '').strip().upper()
    selected_inst = resolve_instrument(symbol_query) if symbol_query else None
    search_error = None
    valid_sources = dict(MarketInstrument.SOURCE_CHOICES)
    requested_source = request.GET.get('source', '').strip().upper()
    if requested_source not in valid_sources:
        requested_source = selected_inst.data_source if selected_inst else 'YAHOO'
    selected_source = requested_source
    source_error = request.GET.get('source_error')

    if symbol_query and symbol_query.lower() not in ['all', 'semua'] and not selected_inst:
        search_error = f"Instrumen pasar dengan kata kunci '{symbol_query}' tidak ditemukan."

    # Cache dinamis adaptif per timeframe (sinkron dengan auto-refresh browser)
    cache_ttl = 30 if tf == '1m' else (60 if tf == '5m' else (120 if tf in ['15m', '30m'] else 300))

    prediction_data = None
    if selected_inst:
        # -------------------------------------------------------------
        # MODE 1 PASAR TERPILIH (Fokus Instrumen & Prediksi 1 Menit)
        # -------------------------------------------------------------
        detail_cache_key = (
            f'dashboard_detail_{selected_inst.symbol}_{tf}_{selected_source}'
        )
        try:
            prediction_data = cache.get(detail_cache_key)
        except Exception as e:
            logger.debug(f"Cache get gagal: {e}")
            prediction_data = None

        if prediction_data is None:
            prediction_data = typed_get_detailed_prediction(
                selected_inst.id, timeframe=tf, data_source=selected_source
            )

            # Jika data di database masih kosong atau kurang dari 15 candle,
            # lakukan auto-sync langsung untuk instrumen ini agar pengguna langsung melihat data!
            if prediction_data and not prediction_data.get('has_enough_data'):
                try:
                    if selected_source == 'IQOPTION':
                        from data_ingestion.iqoption.constants import resolve_active_id
                        from data_ingestion.tasks import fetch_iqoption_prices
                        if not resolve_active_id(selected_inst.symbol)[1]:
                            raise ValueError(
                                f"{selected_inst.symbol} tidak tersedia di IQ Option."
                            )
                        fetch_iqoption_prices(timeframe=tf, symbols=[selected_inst.symbol])
                    else:
                        if selected_inst.symbol.endswith('-OTC'):
                            raise ValueError(
                                f"{selected_inst.symbol} hanya tersedia melalui IQ Option."
                            )
                        from data_ingestion.tasks import fetch_market_prices
                        fetch_market_prices(timeframe=tf, symbols=[selected_inst.symbol])
                    prediction_data = typed_get_detailed_prediction(
                        selected_inst.id, timeframe=tf, data_source=selected_source
                    )
                except Exception as e:
                    logger.warning(
                        "Gagal mengambil data %s untuk %s [%s]: %s",
                        selected_source, selected_inst.symbol, tf, e,
                    )
                    source_error = (
                        f"Gagal mengambil data dari {valid_sources[selected_source]}. "
                        "Periksa koneksi, ketersediaan simbol, dan kredensial sumber data."
                    )

            if prediction_data and not prediction_data.get('has_enough_data') and not source_error:
                source_error = (
                    f"Data dari {valid_sources[selected_source]} belum mencukupi "
                    f"untuk prediksi {selected_inst.symbol} [{tf}]."
                )

            try:
                cache.set(detail_cache_key, prediction_data, timeout=cache_ttl)
            except Exception as e:
                logger.debug(f"Cache set gagal: {e}")

        summary = compute_single_instrument_summary(prediction_data)
        has_data_in_db = MarketData.objects.filter(
            instrument=selected_inst, timeframe=tf, data_source=selected_source
        ).exists()
    else:
        # -------------------------------------------------------------
        # MODE SEMUA PASAR (Tabel Ringkasan Global Multi-Instrumen)
        # -------------------------------------------------------------
        cache_key = f'dashboard_market_data_{tf}_{category_filter or "all"}'
        try:
            dashboard_data = cache.get(cache_key)
        except Exception as e:
            logger.debug(f"Cache get global gagal: {e}")
            dashboard_data = None

        if dashboard_data is None:
            instruments_qs = MarketInstrument.objects.filter(is_active=True)
            if category_filter in ['FOREX', 'CRYPTO', 'STOCK', 'COMMODITY']:
                instruments_qs = instruments_qs.filter(market_category=category_filter)

            dashboard_data = []
            for inst in instruments_qs:
                analysis_result = typed_analyze_instrument_optimized(
                    inst.id, timeframe=tf, data_source=inst.data_source
                )
                if analysis_result:
                    decimals = 5 if ('=X' in inst.symbol or 'EUR' in inst.symbol or 'USD' in inst.symbol and 'BTC' not in inst.symbol) else (2 if (analysis_result.get('close_price') or 0) > 100 else 4)
                    dashboard_data.append({
                        'id': inst.id,
                        'symbol': inst.symbol,
                        'name': inst.name,
                        'category': inst.get_market_category_display(),
                        'date': analysis_result.get('timestamp'),
                        'open': safe_round(analysis_result.get('open_price'), decimals),
                        'high': safe_round(analysis_result.get('high_price'), decimals),
                        'low': safe_round(analysis_result.get('low_price'), decimals),
                        'close': safe_round(analysis_result.get('close_price'), decimals),
                        'volume': safe_round(analysis_result.get('volume'), 2),
                        'sma_5': safe_round(analysis_result.get('SMA_5'), decimals),
                        'sma_20': safe_round(analysis_result.get('SMA_20'), decimals),
                        'ema_9': safe_round(analysis_result.get('EMA_9'), decimals),
                        'ema_21': safe_round(analysis_result.get('EMA_21'), decimals),
                        'rsi_14': safe_round(analysis_result.get('RSI_14'), 2),
                        'macd': safe_round(analysis_result.get('MACD'), decimals),
                        'signal': analysis_result.get('Signal', 'WAIT'),
                        'prediction_direction': analysis_result.get('prediction_direction', 'KONSOLIDASI'),
                        'prob_up': analysis_result.get('probability_up', 50),
                        'prob_down': analysis_result.get('probability_down', 50),
                        'confidence': analysis_result.get('confidence', 'SEDANG'),
                        'candle_pattern': analysis_result.get('candle_pattern', '-'),
                        'change_val': safe_round(analysis_result.get('change_val'), decimals),
                        'change_pct': safe_round(analysis_result.get('change_pct'), 2),
                        'last_update': analysis_result.get('timestamp')
                    })

            try:
                cache.set(cache_key, dashboard_data, timeout=cache_ttl)
            except Exception as e:
                logger.debug(f"Cache set global gagal: {e}")

        summary = compute_summary(dashboard_data)
        has_data_in_db = MarketData.objects.filter(timeframe=tf).exists()

    grouped_instruments = get_instruments_grouped()
    is_synced = request.GET.get('synced') == '1'
    order_opened = request.GET.get('order_opened') == '1'
    order_closed = request.GET.get('order_closed') == '1'
    account_reset = request.GET.get('account_reset') == '1'
    order_error = request.GET.get('order_error') or request.GET.get('error')

    # Integrasi Akun Virtual Paper Trading & Evaluasi Posisi
    virtual_account = None
    open_trades = []
    closed_trades = []
    paper_stats = {}
    auto_setting = None

    try:
        from paper_trading.services import get_or_create_default_account, evaluate_open_positions
        evaluate_open_positions()
        virtual_account = get_or_create_default_account()
        open_trades = list(virtual_account.trades.filter(status='OPEN').select_related('instrument'))
        for ot in open_trades:
            last_c = ot.instrument.price_data.filter(
                timeframe=ot.timeframe,
                data_source=ot.instrument.data_source,
            ).order_by('-timestamp').first()
            curr_p = last_c.close_price if last_c else ot.entry_price
            ot.current_price = curr_p
            ot.floating_pnl = ot.calculate_floating_pnl(curr_p)
            ot.floating_pct = round((ot.floating_pnl / ot.amount) * 100, 2) if ot.amount > 0 else 0.0

        closed_trades = list(virtual_account.trades.exclude(status='OPEN').select_related('instrument')[:25])
        paper_stats = virtual_account.get_stats()
        auto_setting = virtual_account.auto_setting
    except Exception as e:
        logger.warning(f"Gagal memuat data akun paper trading: {e}")

    context = {
        'selected_instrument': selected_inst,
        'prediction_data': prediction_data,
        'data': dashboard_data if not selected_inst else [],
        'active_tf': tf,
        'timeframes': TIMEFRAME_LIST,
        'popular_symbols': POPULAR_SYMBOLS,
        'grouped_instruments': grouped_instruments,
        'active_category': category_filter,
        'summary': summary,
        'has_data_in_db': has_data_in_db,
        'is_synced': is_synced,
        'search_error': search_error,
        'current_symbol': selected_inst.symbol if selected_inst else '',
        'data_sources': MarketInstrument.SOURCE_CHOICES,
        'selected_data_source': selected_source,
        'is_otc_instrument': bool(
            selected_inst and selected_inst.symbol.endswith('-OTC')
        ),
        'source_error': source_error,
        'virtual_account': virtual_account,
        'open_trades': open_trades,
        'closed_trades': closed_trades,
        'paper_stats': paper_stats,
        'auto_setting': auto_setting,
        'order_opened': order_opened,
        'order_closed': order_closed,
        'account_reset': account_reset,
        'order_error': order_error,
        'chart_data_json': json.dumps(prediction_data.get('chart_data', {})) if (prediction_data and prediction_data.get('has_enough_data')) else '{}',
    }

    return render(request, 'trading_dashboard/index.html', context)


def sync_market_data(request):
    """
    Memicu proses penarikan data instan:
    - Jika parameter 'symbol' diberikan: menarik HANYA 1 instrumen (super cepat, ~1 detik).
    - Jika tanpa parameter: menarik seluruh instrumen aktif secara batch.
    """
    tf = request.GET.get('tf', '1d')
    if tf not in VALID_TIMEFRAMES:
        tf = '1d'

    symbol_query = request.GET.get('symbol', '').strip()
    selected_inst = resolve_instrument(symbol_query) if symbol_query else None
    requested_source = request.GET.get('source', '').strip().upper()
    valid_sources = dict(MarketInstrument.SOURCE_CHOICES)
    if requested_source not in valid_sources:
        requested_source = selected_inst.data_source if selected_inst else 'YAHOO'

    if selected_inst:
        # Hapus cache spesifik instrumen ini dan timeframe ini
        try:
            cache.delete(f'dashboard_detail_{selected_inst.symbol}_{tf}')
            cache.delete(
                f'dashboard_detail_{selected_inst.symbol}_{tf}_{requested_source}'
            )
            cache.delete(f'dashboard_market_data_{tf}_all')
            cache.delete(f'dashboard_market_data_{tf}_{selected_inst.market_category}')
        except Exception as e:
            logger.debug(f"Pembersihan cache instrumen dilewati: {e}")

        try:
            if requested_source == 'IQOPTION':
                from data_ingestion.iqoption.constants import resolve_active_id
                from data_ingestion.tasks import fetch_iqoption_prices
                if not resolve_active_id(selected_inst.symbol)[1]:
                    raise ValueError(
                        f"{selected_inst.symbol} tidak tersedia di IQ Option."
                    )
                fetch_iqoption_prices(timeframe=tf, symbols=[selected_inst.symbol])
            else:
                if selected_inst.symbol.endswith('-OTC'):
                    raise ValueError(
                        f"{selected_inst.symbol} hanya tersedia melalui IQ Option."
                    )
                from data_ingestion.tasks import fetch_market_prices
                # Eksekusi langsung secara synchronous agar data tersedia seketika
                fetch_market_prices(timeframe=tf, symbols=[selected_inst.symbol])
        except Exception as e:
            logger.warning(
                "Gagal sinkron %s untuk %s [%s]: %s",
                requested_source, selected_inst.symbol, tf, e,
            )
            return redirect('/?' + urlencode({
                'symbol': selected_inst.symbol,
                'tf': tf,
                'source': requested_source,
                'source_error': (
                    f"Gagal mengambil data dari {valid_sources[requested_source]}. "
                    "Periksa koneksi, ketersediaan simbol, dan kredensial sumber data."
                ),
            }))

        return redirect(
            f'/?symbol={selected_inst.symbol}&tf={tf}'
            f'&source={requested_source}&synced=1'
        )
    else:
        # Sinkronisasi massal seluruh instrumen
        try:
            cache.delete(f'dashboard_market_data_{tf}_all')
            cache.delete(f'dashboard_market_data_{tf}')
            for cat in ['FOREX', 'CRYPTO', 'STOCK', 'COMMODITY']:
                cache.delete(f'dashboard_market_data_{tf}_{cat}')
        except Exception as e:
            logger.debug(f"Pembersihan cache massal dilewati: {e}")

        try:
            from data_ingestion.tasks import fetch_market_prices
            fetch_market_prices.delay(timeframe=tf)
        except Exception:
            from data_ingestion.tasks import fetch_market_prices
            fetch_market_prices(timeframe=tf)

        # Sinkronisasi IQ Option jika ada instrumen aktif IQ Option dan timeframe didukung
        if hasattr(MarketInstrument, 'data_source') and MarketInstrument.objects.filter(is_active=True, data_source='IQOPTION').exists() and tf in ['1m', '5m', '15m', '30m', '1h', '1d']:
            try:
                from data_ingestion.tasks import fetch_iqoption_prices
                fetch_iqoption_prices.delay(timeframe=tf)
            except Exception:
                try:
                    from data_ingestion.tasks import fetch_iqoption_prices
                    fetch_iqoption_prices(timeframe=tf)
                except Exception as e:
                    logger.warning(f"Gagal sinkron massal IQ Option [{tf}]: {e}")

        return redirect(f'/?tf={tf}&synced=1')


def export_csv(request):
    """Mengekspor analisa data instrumen pasar (atau 1 pasar terpilih) ke file CSV"""
    tf = request.GET.get('tf', '1d')
    if tf not in VALID_TIMEFRAMES:
        tf = '1d'

    symbol_query = request.GET.get('symbol', '').strip()
    selected_inst = resolve_instrument(symbol_query) if symbol_query else None
    category_filter = request.GET.get('category', '').strip().upper()
    valid_categories = {choice[0] for choice in MarketInstrument.CATEGORY_CHOICES}
    if category_filter not in valid_categories:
        category_filter = ''

    if selected_inst:
        instruments = [selected_inst]
        filename = f"analisa_{selected_inst.symbol}_{tf}.csv"
    else:
        instruments = MarketInstrument.objects.filter(is_active=True)
        if category_filter:
            instruments = instruments.filter(market_category=category_filter)
            filename = f"analisa_pasar_{category_filter}_{tf}.csv"
        else:
            filename = f"analisa_pasar_{tf}.csv"

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Simbol', 'Nama Aset', 'Kategori', 'Kerangka Waktu', 'Date (Tanggal)',
        'Open (Buka)', 'High (Tertinggi)', 'Low (Terendah)', 'Price (Close)',
        'Volume', 'SMA 5', 'SMA 20', 'EMA 9', 'EMA 21', 'RSI 14', 'MACD',
        'Sinyal Algoritma', 'Prediksi Arah', 'Probabilitas Naik (%)', 'Probabilitas Turun (%)', 'Keyakinan'
    ])

    for inst in instruments:
        result = typed_analyze_instrument_optimized(
            inst.id, timeframe=tf, data_source=inst.data_source
        )
        if result:
            writer.writerow([
                inst.symbol,
                inst.name,
                inst.get_market_category_display(),
                tf,
                result.get('timestamp', ''),
                result.get('open_price', ''),
                result.get('high_price', ''),
                result.get('low_price', ''),
                result.get('close_price', ''),
                result.get('volume', ''),
                result.get('SMA_5', ''),
                result.get('SMA_20', ''),
                result.get('EMA_9', ''),
                result.get('EMA_21', ''),
                result.get('RSI_14', ''),
                result.get('MACD', ''),
                result.get('Signal', ''),
                result.get('prediction_direction', 'KONSOLIDASI'),
                result.get('probability_up', 50),
                result.get('probability_down', 50),
                result.get('confidence', 'SEDANG')
            ])

    return response


def chart_data_api(request):
    """
    API JSON yang mengembalikan deret waktu lilin, volume, EMA, RSI, MACD,
    dan penanda sinyal untuk TradingView Lightweight Charts.
    """
    symbol_query = request.GET.get('symbol', '').strip()
    tf = request.GET.get('tf', '1m').strip()
    data_source = request.GET.get('source', '').strip().upper()
    valid_sources = dict(MarketInstrument.SOURCE_CHOICES)
    if data_source and data_source not in valid_sources:
        return JsonResponse(
            {'success': False, 'error': 'Sumber data tidak valid.'}, status=400
        )
    if tf not in VALID_TIMEFRAMES:
        tf = '1m'

    inst = resolve_instrument(symbol_query) if symbol_query else None
    if not inst:
        return JsonResponse({'success': False, 'error': f"Instrumen '{symbol_query}' tidak ditemukan."}, status=404)

    prediction_data = typed_get_detailed_prediction(
        inst.id, timeframe=tf, data_source=data_source or inst.data_source
    )
    if not prediction_data or not prediction_data.get('has_enough_data'):
        return JsonResponse({'success': False, 'error': f"Data lilin {inst.symbol} [{tf}] belum mencukupi."}, status=400)

    return JsonResponse({
        'success': True,
        'symbol': inst.symbol,
        'timeframe': tf,
        'chart_data': prediction_data.get('chart_data', {})
    })
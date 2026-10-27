#data_ingestion/management/commands/stream_crypto_realtime.py
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
import websockets

# Izinkan operasi ORM sinkron di dalam event loop asyncio untuk skrip CLI
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

from django.core.management.base import BaseCommand
from django.core.cache import cache
from asgiref.sync import sync_to_async
from data_ingestion.models import MarketInstrument, MarketData
from technical_indicators.services import get_detailed_prediction
from trading_dashboard.views import resolve_instrument

logger = logging.getLogger(__name__)

PAIR_MAP = {
    'BTC-USD': 'btcusdt',
    'BTC': 'btcusdt',
    'ETH-USD': 'ethusdt',
    'ETH': 'ethusdt',
    'SOL-USD': 'solusdt',
    'SOL': 'solusdt',
    'BNB-USD': 'bnbusdt',
    'BNB': 'bnbusdt',
}

class Command(BaseCommand):
    help = 'Aliran data lilin 1m real-time langsung via WebSocket Binance, update DB, dan prediksi otomatis per menit'

    def add_arguments(self, parser):
        parser.add_argument('--symbol', type=str, default='BTC-USD', help='Simbol instrumen kripto (contoh: BTC-USD, ETH-USD)')
        parser.add_argument('--max-candles', type=int, default=0, help='Hentikan setelah N candle (0 = berjalan terus)')

    def handle(self, *args, **options):
        symbol_query = options['symbol']
        max_candles = options['max_candles']

        inst = resolve_instrument(symbol_query)
        if not inst:
            # Otomatis buat instrumen jika belum terdaftar
            inst = MarketInstrument.objects.create(
                symbol=symbol_query.upper(),
                name=f"{symbol_query.upper()} Realtime",
                market_category='CRYPTO',
                is_active=True
            )

        binance_pair = PAIR_MAP.get(inst.symbol, inst.symbol.replace('-USD', 'usdt').replace('=', '').lower())

        self.stdout.write(self.style.NOTICE(f"\n========================================================"))
        self.stdout.write(self.style.NOTICE(f"🚀 FASE 2: STREAMING WEBSOCKET REAL-TIME (BINANCE FEED)"))
        self.stdout.write(self.style.NOTICE(f"========================================================"))
        self.stdout.write(f"• Instrumen DB  : {inst.symbol} ({inst.name})")
        self.stdout.write(f"• Pair WebSocket : {binance_pair.upper()}")
        self.stdout.write(f"• Latensi Target : < 50 milidetik")
        self.stdout.write(f"• Dasbor URL     : http://127.0.0.1:8000/?symbol={inst.symbol}&tf=1m\n")
        self.stdout.write("Tekan Ctrl+C kapan saja untuk menghentikan streaming.\n")

        try:
            asyncio.run(self.run_stream(inst, binance_pair, max_candles))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n🛑 Streaming dihentikan oleh pengguna."))

    async def run_stream(self, inst, binance_pair, max_candles):
        url = f"wss://stream.binance.com:9443/ws/{binance_pair}@kline_1m"
        self.stdout.write(f"📡 Menghubungkan ke {url}...")

        candle_count = 0
        correct_count = 0
        last_prediction = None
        last_pred_price = None

        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            self.stdout.write(self.style.SUCCESS("✅ Terhubung ke Binance WebSocket Real-Time Feed!"))
            self.stdout.write("⏳ Mendengarkan tick lilin 1 menit...\n")

            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                if 'k' not in data:
                    continue

                k = data['k']
                is_closed = k['x']
                curr_price = float(k['c'])
                high_price = float(k['h'])
                low_price = float(k['l'])
                open_price = float(k['o'])
                vol = float(k['v'])

                # Timestamp UTC aware
                ts_ms = k['t']
                candle_time = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                waktu_str = candle_time.strftime('%H:%M:%S')

                if is_closed:
                    candle_count += 1
                    self.stdout.write("\n" + "=" * 60)
                    self.stdout.write(self.style.SUCCESS(
                        f"🔔 [LILIN 1M SELESAI #{candle_count}] Jam: {waktu_str} UTC | "
                        f"Open: {open_price} | Close: {curr_price} | Vol: {vol:.2f}"
                    ))

                    # 1. Simpan lilin ke Database SQLite (Upsert)
                    MarketData.objects.update_or_create(
                        instrument=inst,
                        timeframe='1m',
                        data_source=inst.data_source,
                        timestamp=candle_time,
                        defaults={
                            'open_price': open_price,
                            'high_price': high_price,
                            'low_price': low_price,
                            'close_price': curr_price,
                            'volume': vol,
                        }
                    )

                    # 1b. Evaluasi Posisi Paper Trading (Cek sentuhan Take Profit / Stop Loss)
                    try:
                        from paper_trading.services import evaluate_open_positions
                        closed_pt = evaluate_open_positions()
                        if closed_pt > 0:
                            self.stdout.write(self.style.SUCCESS(f"   🎯 [PAPER TRADING] {closed_pt} posisi virtual mencapai TP/SL."))
                    except Exception:
                        pass

                    # 2. Evaluasi Prediksi Lilin Sebelumnya (Jika ada)
                    if last_prediction and last_pred_price:
                        delta = curr_price - last_pred_price
                        actual_dir = 'NAIK' if delta > 0 else ('TURUN' if delta < 0 else 'FLAT')
                        pred_dir = last_prediction.get('direction')
                        is_correct = (pred_dir == actual_dir)

                        if is_correct:
                            correct_count += 1
                            status_badge = self.style.SUCCESS("✅ TEPAT (BENAR)")
                        else:
                            status_badge = self.style.ERROR("❌ MELESET (SALAH)")

                        win_rate = (correct_count / candle_count) * 100
                        self.stdout.write(
                            f"🎯 EVALUASI PREDIKSI SEBELUMNYA: "
                            f"Prediksi: {pred_dir} ({last_prediction.get('prob_up')}%) vs Hasil Riil: {actual_dir} ({delta:+.2f}) "
                            f"──► {status_badge} | Akurasi Sesi: {correct_count}/{candle_count} ({win_rate:.1f}%)"
                        )

                    # 3. Jalankan Mesin Prediksi untuk Lilin 1 Menit Berikutnya
                    pred_res = get_detailed_prediction(
                        inst.id, timeframe='1m', data_source=inst.data_source
                    )
                    if pred_res and pred_res.get('has_enough_data'):
                        p = pred_res['prediction']
                        last_prediction = p
                        last_pred_price = curr_price

                        # Update Redis Cache agar Web Dashboard langsung sinkron instan!
                        try:
                            cache.set(f'dashboard_detail_{inst.symbol}_1m', pred_res, timeout=30)
                            cache.set(f'dashboard_detail_{inst.symbol}_1m_{inst.data_source}', pred_res, timeout=30)
                            cache.delete('dashboard_market_data_1m_all')
                            cache.delete(f'dashboard_market_data_1m_{inst.market_category}')
                        except Exception as cache_err:
                            logger.debug(f"Pembaruan cache dilewati: {cache_err}")

                        dir_color = self.style.SUCCESS if p['direction'] == 'NAIK' else (self.style.ERROR if p['direction'] == 'TURUN' else self.style.WARNING)
                        self.stdout.write(dir_color(
                            f"🔮 [PREDIKSI 1M KE DEPAN]: ▲ {p['direction']} (Peluang Naik: {p['prob_up']}% | Turun: {p['prob_down']}%) "
                            f"| Keyakinan: {p['confidence']} | Target TP: {p['target_up']} | SL: {p['stop_loss_buy'] if p['direction'] == 'NAIK' else p['stop_loss_sell']}"
                        ))
                        self.stdout.write(f"   Catatan Scalper: {p['recommendation']}")

                    self.stdout.write("=" * 60 + "\n")

                    if max_candles > 0 and candle_count >= max_candles:
                        self.stdout.write(self.style.SUCCESS(f"🏁 Mencapai batas {max_candles} candle. Streaming selesai."))
                        break
                else:
                    # Update status tick berjalan pada baris yang sama
                    pct_change = ((curr_price - open_price) / open_price * 100) if open_price > 0 else 0
                    tanda = "+" if pct_change >= 0 else ""
                    self.stdout.write(
                        f"\r⏱️ [{waktu_str}] {inst.symbol} Tick: {curr_price:.2f} ({tanda}{pct_change:.2f}%) "
                        f"| H: {high_price:.2f} | L: {low_price:.2f} | Vol: {vol:.2f}",
                        ending=''
                    )

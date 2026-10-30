#data_ingestion/management/commands/stream_iqoption_realtime.py
import asyncio
import os
import logging
from datetime import datetime, timezone

# Izinkan operasi ORM sinkron di dalam event loop asyncio untuk skrip CLI
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

from django.core.management.base import BaseCommand
from django.core.cache import cache
from asgiref.sync import sync_to_async
from data_ingestion.models import MarketData
from data_ingestion.iqoption.constants import resolve_active_id, TIMEFRAME_TO_SECONDS
from data_ingestion.iqoption.client import IQOptionClient, IQOptionAuthError
from data_ingestion.iqoption.service import get_or_create_iqoption_instrument
from technical_indicators.services import get_detailed_prediction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Aliran data lilin real-time langsung via WebSocket IQ Option Traderoom (iqoption.com/traderoom), evaluasi prediksi & rekomendasi scalper'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbol',
            type=str,
            default='EURUSD-OTC',
            help='Simbol instrumen IQ Option (contoh: EURUSD-OTC, GBPUSD-OTC, EURUSD, BTCUSD, XAUUSD)'
        )
        parser.add_argument(
            '--timeframe',
            '-tf',
            type=str,
            default='1m',
            choices=['1m', '5m', '15m'],
            help='Timeframe lilin untuk streaming dan prediksi (default: 1m)'
        )
        parser.add_argument(
            '--max-candles',
            type=int,
            default=0,
            help='Hentikan setelah N candle tertutup (0 = berjalan terus tanpa henti)'
        )
        parser.add_argument(
            '--ssid',
            type=str,
            default=None,
            help='Token SSID IQ Option (bisa juga diset di .env sebagai IQOPTION_SSID)'
        )
        parser.add_argument(
            '--email',
            type=str,
            default=None,
            help='Email akun IQ Option (opsional)'
        )
        parser.add_argument(
            '--password',
            type=str,
            default=None,
            help='Password akun IQ Option (opsional)'
        )
        parser.add_argument(
            '--demo-feed',
            action='store_true',
            help='Gunakan mode simulasi demo feed untuk pengujian tanpa login'
        )

    def handle(self, *args, **options):
        symbol_query = options['symbol']
        timeframe = options['timeframe']
        max_candles = options['max_candles']
        ssid = options['ssid'] or os.environ.get('IQOPTION_SSID')
        email = options['email'] or os.environ.get('IQOPTION_EMAIL')
        password = options['password'] or os.environ.get('IQOPTION_PASSWORD')
        demo_feed = options['demo_feed']

        name, active_id = resolve_active_id(symbol_query)
        if not active_id:
            self.stdout.write(self.style.ERROR(f"❌ Simbol IQ Option '{symbol_query}' tidak dikenali."))
            return

        inst = get_or_create_iqoption_instrument(name)

        self.stdout.write(self.style.NOTICE(f"\n========================================================"))
        self.stdout.write(self.style.NOTICE(f"🚀 FASE 4: STREAMING REAL-TIME IQ OPTION TRADEROOM"))
        self.stdout.write(self.style.NOTICE(f"========================================================"))
        self.stdout.write(f"• Instrumen DB    : {inst.symbol} ({inst.name})")
        self.stdout.write(f"• Active ID IQ    : {active_id} ({name})")
        self.stdout.write(f"• Timeframe       : {timeframe} ({TIMEFRAME_TO_SECONDS.get(timeframe, 60)} detik)")
        self.stdout.write(f"• Mode Feed       : {'Simulasi Demo Feed' if demo_feed else 'Live WebSocket IQ Option'}")
        self.stdout.write(f"• Dasbor URL      : http://127.0.0.1:8000/?symbol={inst.symbol}&tf={timeframe}\n")

        if not demo_feed and not ssid and not (email and password):
            self.stdout.write(self.style.WARNING("⚠️ PERHATIAN: Kredensial IQ Option belum diatur di .env!"))
            self.stdout.write("💡 CARA CEPAT KONEKSI DENGAN SSID BROWSER:")
            self.stdout.write("1. Buka https://iqoption.com/traderoom di browser dan login.")
            self.stdout.write("2. Tekan F12 > Storage/Application > Cookies > 'https://iqoption.com'.")
            self.stdout.write("3. Salin nilai cookie 'ssid'.")
            self.stdout.write("4. Simpan di .env sebagai: IQOPTION_SSID=...")
            self.stdout.write("\n💡 Atau gunakan flag --demo-feed untuk menguji streaming sekarang:")
            self.stdout.write(f"   python manage.py stream_iqoption_realtime --symbol {inst.symbol} --demo-feed\n")
            return

        self.stdout.write("Tekan Ctrl+C kapan saja untuk menghentikan streaming.\n")

        try:
            asyncio.run(self.run_stream(inst, name, active_id, timeframe, max_candles, ssid, email, password, demo_feed))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n🛑 Streaming IQ Option dihentikan oleh pengguna."))

    async def run_stream(self, inst, name, active_id, timeframe, max_candles, ssid, email, password, demo_feed):
        client = IQOptionClient(ssid=ssid, email=email, password=password, demo_feed=demo_feed)
        
        if not demo_feed:
            self.stdout.write(f"📡 Menghubungkan ke WebSocket IQ Option Traderoom...")
            try:
                await client.connect_ws()
                self.stdout.write(self.style.SUCCESS("✅ Terhubung dan terotentikasi di IQ Option Traderoom!"))
            except IQOptionAuthError as e:
                self.stdout.write(self.style.ERROR(f"❌ {e}"))
                return
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Gagal koneksi: {e}"))
                return
        else:
            self.stdout.write(self.style.SUCCESS("✅ Mode Demo Feed aktif. Menghasilkan live ticks IQ Option..."))

        self.stdout.write(f"⏳ Mendengarkan tick & lilin {timeframe}...\n")

        candle_count = 0
        correct_count = 0
        last_prediction = None
        last_pred_price = None

        async def handle_tick(tick_data):
            curr_p = tick_data['close']
            open_p = tick_data['open']
            high_p = tick_data['high']
            low_p = tick_data['low']
            vol = tick_data['volume']
            pct_change = ((curr_p - open_p) / open_p * 100) if open_p > 0 else 0
            tanda = "+" if pct_change >= 0 else ""
            waktu_str = tick_data['timestamp'].strftime('%H:%M:%S')

            decimals = 5 if curr_p < 500 else 2
            self.stdout.write(
                f"\r⏱️ [{waktu_str}] {inst.symbol} Tick: {curr_p:.{decimals}f} ({tanda}{pct_change:.2f}%) "
                f"| H: {high_p:.{decimals}f} | L: {low_p:.{decimals}f} | Vol: {vol:.1f}",
                ending=''
            )

        async def handle_candle_close(closed_candle):
            nonlocal candle_count, correct_count, last_prediction, last_pred_price
            candle_count += 1

            c_time = closed_candle['timestamp']
            open_p = closed_candle['open']
            high_p = closed_candle['high']
            low_p = closed_candle['low']
            close_p = closed_candle['close']
            vol = closed_candle['volume']
            waktu_str = c_time.strftime('%H:%M:%S')
            decimals = 5 if close_p < 500 else 2

            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.SUCCESS(
                f"🔔 [LILIN IQ OPTION {timeframe.upper()} SELESAI #{candle_count}] Jam: {waktu_str} UTC | "
                f"Open: {open_p:.{decimals}f} | Close: {close_p:.{decimals}f} | Vol: {vol:.1f}"
            ))

            # 1. Simpan lilin yang selesai ke Database SQLite3
            await sync_to_async(MarketData.objects.update_or_create)(
                instrument=inst,
                timeframe=timeframe,
                data_source='IQOPTION',
                timestamp=c_time,
                defaults={
                    'open_price': open_p,
                    'high_price': high_p,
                    'low_price': low_p,
                    'close_price': close_p,
                    'volume': vol,
                }
            )

            # 1b. Evaluasi Posisi Paper Trading (Cek sentuhan Take Profit / Stop Loss)
            try:
                from paper_trading.services import evaluate_open_positions
                closed_pt = await sync_to_async(evaluate_open_positions)()
                if closed_pt > 0:
                    self.stdout.write(self.style.SUCCESS(f"   🎯 [PAPER TRADING] {closed_pt} posisi virtual mencapai TP/SL."))
            except Exception:
                pass

            # 2. Evaluasi Prediksi Lilin Sebelumnya
            if last_prediction and last_pred_price:
                delta = close_p - last_pred_price
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
                    f"Prediksi: {pred_dir} ({last_prediction.get('prob_up')}%) vs Hasil Riil: {actual_dir} ({delta:+.{decimals}f}) "
                    f"──► {status_badge} | Akurasi Sesi: {correct_count}/{candle_count} ({win_rate:.1f}%)"
                )

            # 3. Jalankan Mesin Prediksi untuk Lilin Berikutnya
            pred_res = await sync_to_async(get_detailed_prediction)(inst.id, timeframe=timeframe, data_source='IQOPTION')
            if pred_res and pred_res.get('has_enough_data'):
                p = pred_res['prediction']
                last_prediction = p
                last_pred_price = close_p

                # Update Redis Cache agar Web Dashboard langsung sinkron instan
                try:
                    cache.set(f'dashboard_detail_{inst.symbol}_{timeframe}', pred_res, timeout=30)
                    cache.set(f'dashboard_detail_{inst.symbol}_{timeframe}_IQOPTION', pred_res, timeout=30)
                    cache.delete(f'dashboard_market_data_{timeframe}_all')
                    cache.delete(f'dashboard_market_data_{timeframe}_{inst.market_category}')
                except Exception as cache_err:
                    logger.debug(f"Pembaruan cache IQ Option dilewati: {cache_err}")

                dir_color = self.style.SUCCESS if p['direction'] == 'NAIK' else (
                    self.style.ERROR if p['direction'] == 'TURUN' else self.style.WARNING
                )
                self.stdout.write(dir_color(
                    f"🔮 [PREDIKSI {timeframe.upper()} KE DEPAN]: ▲ {p['direction']} "
                    f"(Peluang Naik: {p['prob_up']}% | Turun: {p['prob_down']}%) "
                    f"| Keyakinan: {p['confidence']} | Target TP: {p['target_up']} | SL: {p['stop_loss_buy'] if p['direction'] == 'NAIK' else p['stop_loss_sell']}"
                ))
                self.stdout.write(f"   Catatan Scalper: {p['recommendation']}")

            self.stdout.write("=" * 60 + "\n")

        await client.stream_candles(
            active_id_or_name=name,
            timeframe=timeframe,
            on_tick=handle_tick,
            on_candle_close=handle_candle_close,
            max_candles=max_candles
        )

        await client.close()

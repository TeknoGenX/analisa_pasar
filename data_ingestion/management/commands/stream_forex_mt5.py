import time
from datetime import datetime, timezone
from django.core.management.base import BaseCommand
from django.core.cache import cache
from data_ingestion.models import MarketInstrument, MarketData
from technical_indicators.services import get_detailed_prediction
from trading_dashboard.views import resolve_instrument

class Command(BaseCommand):
    help = 'Streaming lilin 1M Forex real-time langsung dari MetaTrader 5 (MT5 API) ke SQLite & Redis'

    def add_arguments(self, parser):
        parser.add_argument('--symbol', type=str, default='EURUSD', help='Simbol Forex di MT5 (contoh: EURUSD, GBPUSD)')
        parser.add_argument('--account', type=int, default=None, help='Nomor akun MT5 (opsional)')
        parser.add_argument('--password', type=str, default=None, help='Password akun MT5 (opsional)')
        parser.add_argument('--server', type=str, default=None, help='Nama server broker MT5 (opsional)')

    def handle(self, *args, **options):
        symbol_mt5 = options['symbol'].upper()
        self.stdout.write(self.style.NOTICE(f"\n========================================================"))
        self.stdout.write(self.style.NOTICE(f"🏛️ FASE 3: INTEGRASI FOREX REAL-TIME (METATRADER 5 API)"))
        self.stdout.write(self.style.NOTICE(f"========================================================"))

        try:
            import MetaTrader5 as mt5
        except ImportError:
            self.stdout.write(self.style.ERROR("❌ Modul 'MetaTrader5' belum terpasang di environment ini."))
            self.stdout.write("\n💡 PANDUAN PENYIAPAN METATRADER 5:")
            self.stdout.write("1. Pasang paket python: pip install MetaTrader5")
            self.stdout.write("2. Di sistem Linux (Parrot OS / Ubuntu), jalankan MT5 via Wine:")
            self.stdout.write("   sudo apt install wine64")
            self.stdout.write("   wine mt5setup.exe")
            self.stdout.write("   (Atau jalankan skrip ini di Windows/VPS yang terpasang terminal MT5).")
            self.stdout.write("3. Buka akun Demo gratis di broker mana pun (misal: IC Markets, Exness, FXCM).")
            self.stdout.write("========================================================\n")
            return

        # Inisialisasi MT5
        init_kwargs = {}
        if options['account']:
            init_kwargs['login'] = options['account']
        if options['password']:
            init_kwargs['password'] = options['password']
        if options['server']:
            init_kwargs['server'] = options['server']

        self.stdout.write("⏳ Menghubungkan ke terminal MetaTrader 5...")
        if not mt5.initialize(**init_kwargs):
            self.stdout.write(self.style.ERROR(f"❌ Gagal inisialisasi MT5: {mt5.last_error()}"))
            return

        self.stdout.write(self.style.SUCCESS("✅ Berhasil terhubung ke MetaTrader 5!"))

        # Cari instrumen di DB lokal
        inst = resolve_instrument(symbol_mt5) or resolve_instrument(f"{symbol_mt5}=X")
        if not inst:
            inst = MarketInstrument.objects.create(
                symbol=f"{symbol_mt5}=X",
                name=f"{symbol_mt5} Forex Realtime",
                market_category='FOREX',
                is_active=True
            )

        self.stdout.write(f"• Instrumen DB  : {inst.symbol} ({inst.name})")
        self.stdout.write(f"• Simbol MT5    : {symbol_mt5}")
        self.stdout.write(f"• Dasbor URL    : http://127.0.0.1:8000/?symbol={inst.symbol}&tf=1m")
        self.stdout.write("Mendengarkan penutupan bar candle M1... Tekan Ctrl+C untuk berhenti.\n")

        last_candle_time = None
        last_prediction = None
        last_pred_price = None
        candle_count = 0
        correct_count = 0

        try:
            while True:
                # Ambil 2 candle M1 terakhir dari MT5
                rates = mt5.copy_rates_from_pos(symbol_mt5, mt5.TIMEFRAME_M1, 0, 2)
                if rates is None or len(rates) < 2:
                    time.sleep(1)
                    continue

                # Candle yang baru saja ditutup adalah rates[-2]
                closed_rate = rates[-2]
                candle_ts = datetime.fromtimestamp(closed_rate['time'], tz=timezone.utc)

                if last_candle_time is None or candle_ts > last_candle_time:
                    last_candle_time = candle_ts
                    candle_count += 1

                    open_p = float(closed_rate['open'])
                    high_p = float(closed_rate['high'])
                    low_p = float(closed_rate['low'])
                    close_p = float(closed_rate['close'])
                    vol = float(closed_rate['tick_volume'])

                    self.stdout.write("\n" + "=" * 60)
                    self.stdout.write(self.style.SUCCESS(
                        f"🔔 [LILIN MT5 1M SELESAI #{candle_count}] Jam: {candle_ts.strftime('%H:%M:%S')} UTC | "
                        f"Open: {open_p:.5f} | Close: {close_p:.5f} | Vol: {vol}"
                    ))

                    # 1. Simpan ke database
                    MarketData.objects.update_or_create(
                        instrument=inst,
                        timeframe='1m',
                        timestamp=candle_ts,
                        defaults={
                            'open_price': open_p,
                            'high_price': high_p,
                            'low_price': low_p,
                            'close_price': close_p,
                            'volume': vol,
                        }
                    )

                    # 2. Evaluasi Prediksi Sebelumnya
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
                            f"🎯 EVALUASI PREDIKSI: Prediksi: {pred_dir} vs Riil: {actual_dir} ({delta:+.5f}) "
                            f"──► {status_badge} | Akurasi: {correct_count}/{candle_count} ({win_rate:.1f}%)"
                        )

                    # 3. Jalankan Prediksi Lilin 1 Menit Berikutnya
                    pred_res = get_detailed_prediction(inst.id, timeframe='1m')
                    if pred_res and pred_res.get('has_enough_data'):
                        p = pred_res['prediction']
                        last_prediction = p
                        last_pred_price = close_p

                        # Update Redis Cache
                        cache.set(f'dashboard_detail_{inst.symbol}_1m', pred_res, timeout=30)
                        cache.delete(f'dashboard_market_data_1m_all')

                        dir_color = self.style.SUCCESS if p['direction'] == 'NAIK' else (self.style.ERROR if p['direction'] == 'TURUN' else self.style.WARNING)
                        self.stdout.write(dir_color(
                            f"🔮 [PREDIKSI 1M BERIKUTNYA]: ▲ {p['direction']} (Peluang Naik: {p['prob_up']}% | Turun: {p['prob_down']}%) "
                            f"| Keyakinan: {p['confidence']} | Target TP: {p['target_up']} | SL: {p['stop_loss_buy'] if p['direction'] == 'NAIK' else p['stop_loss_sell']}"
                        ))

                    self.stdout.write("=" * 60 + "\n")

                # Cek tick harga berjalan (Live Tick)
                tick = mt5.symbol_info_tick(symbol_mt5)
                if tick:
                    self.stdout.write(
                        f"\r⏱️ [{datetime.now().strftime('%H:%M:%S')}] {symbol_mt5} Tick ── Bid: {tick.bid:.5f} | Ask: {tick.ask:.5f} | Spread: {(tick.ask - tick.bid)*10000:.1f} pips",
                        ending=''
                    )

                time.sleep(0.5)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n🛑 Dihentikan oleh pengguna."))
        finally:
            mt5.shutdown()

# data_ingestion/management/commands/validate_model.py

import pandas as pd
import pandas_ta as ta
from django.core.management.base import BaseCommand

from data_ingestion.models import MarketData, MarketInstrument
from technical_indicators.services import (
    calculate_prediction_score,
    get_higher_timeframe_bias,
)
from trading_dashboard.views import resolve_instrument


class Command(BaseCommand):
    help = (
        'Validasi ilmiah & backtesting walk-forward akurasi prediksi model 1m/5m'
        ' pada data riwayat pasar'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbol',
            type=str,
            default='EURUSD=X',
            help='Simbol instrumen (contoh: EURUSD=X, BTC-USD)',
        )
        parser.add_argument(
            '--timeframe',
            type=str,
            default='1m',
            help='Kerangka waktu (contoh: 1m, 5m, 15m)',
        )
        parser.add_argument(
            '--candles',
            type=int,
            default=300,
            help='Jumlah candle historis yang diuji (default: 300)',
        )
        parser.add_argument(
            '--min-conf',
            type=int,
            default=58,
            help=(
                'Batas minimum probabilitas persen untuk ambil posisi (default:'
                ' 58)'
            ),
        )

    def handle(self, *args, **options):
        symbol_query = options['symbol']
        tf = options['timeframe']
        candles_limit = options['candles']
        min_conf = options['min_conf']

        inst = resolve_instrument(symbol_query)
        if not inst:
            self.stdout.write(
                self.style.ERROR(
                    f"❌ Instrumen '{symbol_query}' tidak ditemukan."
                )
            )
            return

        self.stdout.write(
            self.style.NOTICE(
                "\n========================================================"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "🔬 EKSPERIMEN RISET: VALIDASI WALK-FORWARD MODEL PREDIKSI"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "========================================================"
            )
        )
        self.stdout.write(f"Instrumen    : {inst.symbol} ({inst.name})")
        self.stdout.write(f"Timeframe    : {tf}")
        self.stdout.write(f"Sampel Uji   : {candles_limit} candle terakhir")
        self.stdout.write(f"Filter Sinyal: Probabilitas >= {min_conf}%\n")

        qs = MarketData.objects.filter(
            instrument=inst,
            timeframe=tf,
            data_source=inst.data_source,
        ).order_by('timestamp')

        total_in_db = qs.count()
        if total_in_db < 40:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️ Data candle di database baru {total_in_db}. Dibutuhkan"
                    " minimal 40 candle."
                )
            )
            return

        records = list(
            qs.values(
                'timestamp',
                'open_price',
                'high_price',
                'low_price',
                'close_price',
                'volume',
            )[:candles_limit]
        )

        df = pd.DataFrame.from_records(records)
        df.sort_values('timestamp', ascending=True, inplace=True)
        df.set_index('timestamp', inplace=True)

        # Indikator Dasar
        df['SMA_5'] = ta.sma(df['close_price'], length=5)
        df['SMA_20'] = ta.sma(df['close_price'], length=min(20, len(df)))
        df['EMA_9'] = ta.ema(df['close_price'], length=9)
        df['EMA_21'] = ta.ema(df['close_price'], length=min(21, len(df)))
        df['RSI_14'] = ta.rsi(df['close_price'], length=14)
        df['ATR_14'] = ta.atr(
            df['high_price'],
            df['low_price'],
            df['close_price'],
            length=min(14, len(df)),
        )

        stoch = ta.stochrsi(
            df['close_price'], length=14, rsi_length=14, k=3, d=3
        )
        if stoch is not None and not stoch.empty:
            df['STOCH_K'] = stoch.iloc[:, 0]
            df['STOCH_D'] = stoch.iloc[:, 1]
        else:
            df['STOCH_K'] = None
            df['STOCH_D'] = None

        macd = ta.macd(df['close_price'])
        if macd is not None and not macd.empty:
            df['MACD'] = macd.iloc[:, 0]
            df['MACD_Hist'] = macd.iloc[:, 1]
        else:
            df['MACD'] = None
            df['MACD_Hist'] = None

        # Inisialisasi Metrik Evaluasi
        total_eval = 0
        correct_predictions = 0
        buy_total = 0
        buy_correct = 0
        sell_total = 0
        sell_correct = 0
        high_conf_total = 0
        high_conf_correct = 0
        total_gain_points = 0.0
        total_loss_points = 0.0
        win_rate = 0.0

        for i in range(30, len(df) - 1):
            sub_df = df.iloc[: i + 1]
            pred = calculate_prediction_score(sub_df)
            dir_pred = pred['direction']
            max_prob = max(pred['prob_up'], pred['prob_down'])

            if max_prob < min_conf or dir_pred == 'KONSOLIDASI':
                continue

            curr_close = float(sub_df.iloc[-1]['close_price'])
            next_close = float(df.iloc[i + 1]['close_price'])
            delta = next_close - curr_close

            if delta == 0:
                continue

            actual_dir = 'NAIK' if delta > 0 else 'TURUN'
            is_hit = dir_pred == actual_dir

            total_eval += 1
            if is_hit:
                correct_predictions += 1
                total_gain_points += abs(delta)
            else:
                total_loss_points += abs(delta)

            if dir_pred == 'NAIK':
                buy_total += 1
                if is_hit:
                    buy_correct += 1
            elif dir_pred == 'TURUN':
                sell_total += 1
                if is_hit:
                    sell_correct += 1

            if pred['confidence'] == 'TINGGI':
                high_conf_total += 1
                if is_hit:
                    high_conf_correct += 1

        self.stdout.write(
            self.style.SUCCESS("📊 HASIL EVALUASI KUANTITATIF (WALK-FORWARD):")
        )
        self.stdout.write("--------------------------------------------------------")
        self.stdout.write(f"• Total Candle Diuji   : {len(df)} candle")
        self.stdout.write(f"• Total Sinyal Terpicu : {total_eval} sinyal")

        if total_eval > 0:
            win_rate = (correct_predictions / total_eval) * 100
            self.stdout.write(
                self.style.SUCCESS(
                    f"• Akurasi Keseluruhan (Win Rate) : {correct_predictions}/{total_eval} ({win_rate:.1f}%)"
                )
            )
        else:
            self.stdout.write(
                "• Tidak ada sinyal yang memenuhi kriteria minimum confidence."
            )
            return

        if high_conf_total > 0:
            hc_wr = (high_conf_correct / high_conf_total) * 100
            self.stdout.write(
                self.style.SUCCESS(
                    f"• Win Rate Keyakinan TINGGI     : {high_conf_correct}/{high_conf_total} ({hc_wr:.1f}%)"
                )
            )

        if buy_total > 0:
            buy_wr = (buy_correct / buy_total) * 100
            self.stdout.write(
                f"• Akurasi Sinyal BUY (Naik)     : {buy_correct}/{buy_total} ({buy_wr:.1f}%)"
            )

        if sell_total > 0:
            sell_wr = (sell_correct / sell_total) * 100
            self.stdout.write(
                f"• Akurasi Sinyal SELL (Turun)   : {sell_correct}/{sell_total} ({sell_wr:.1f}%)"
            )

        profit_factor = (
            (total_gain_points / total_loss_points)
            if total_loss_points > 0
            else 999.0
        )
        self.stdout.write(f"• Total Poin Keuntungan         : +{total_gain_points:.5f}")
        self.stdout.write(f"• Total Poin Kerugian           : -{total_loss_points:.5f}")

        pf_color = (
            self.style.SUCCESS if profit_factor >= 1.2 else self.style.WARNING
        )
        self.stdout.write(
            pf_color(
                f"• Rasio Profit Factor           : {profit_factor:.2f} (Target Riset: >= 1.50)"
            )
        )

        self.stdout.write("\n💡 KESIMPULAN RISET:")
        if win_rate >= 55.0 and profit_factor >= 1.2:
            self.stdout.write(
                self.style.SUCCESS(
                    "✅ Model memiliki edge probabilitas statistik yang positif pada data ini!"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️ Pasar di periode ini memiliki noise tinggi atau pergerakan flatline/sideways."
                )
            )
            self.stdout.write(
                " Saran: Tingkatkan parameter --min-conf ke 65% atau gunakan filter Multi-Timeframe M15/M5."
            )

        self.stdout.write(
            "========================================================\n"
        )
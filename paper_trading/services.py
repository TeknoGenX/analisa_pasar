#paper_trading/services.py
import logging
from django.db import transaction
from django.utils import timezone
from data_ingestion.models import MarketInstrument, MarketData
from technical_indicators.services import get_detailed_prediction
from .models import VirtualAccount, AutoTradeSetting, PaperTrade

logger = logging.getLogger(__name__)


def get_or_create_default_account():
    """
    Mengambil atau membuat akun simulasi default dengan saldo modal awal $10,000.
    """
    account = VirtualAccount.objects.filter(is_active=True).first()
    if not account:
        account = VirtualAccount.objects.create(
            name='Akun Simulasi Utama',
            currency='USD',
            initial_balance=10000.0,
            balance=10000.0,
            is_active=True
        )

    # Pastikan konfigurasi Auto-Trade selalu ada
    AutoTradeSetting.objects.get_or_create(
        account=account,
        defaults={
            'is_enabled': False,
            'trade_amount': 100.0,
            'min_probability': 70,
            'only_strong_signals': True,
            'max_open_positions': 5,
            'use_atr_tp_sl': True
        }
    )

    return account


@transaction.atomic
def open_paper_trade(
    account,
    instrument,
    order_type,
    amount=100.0,
    timeframe='1m',
    entry_price=None,
    take_profit=None,
    stop_loss=None,
    is_auto_trade=False,
    signal_info='',
    notes=''
):
    """
    Membuka posisi perdagangan virtual baru (BUY / SELL).
    Memvalidasi ketersediaan saldo, mengalokasikan margin, dan menyimpan catatan transaksi.
    """
    amount = float(amount)
    if amount <= 0:
        raise ValueError("Nominal trading harus lebih besar dari $0.")

    if account.balance < amount:
        raise ValueError(f"Saldo kas tidak mencukupi (${account.balance:,.2f} tersedia, butuh ${amount:,.2f}).")

    # Ambil harga entri terkini jika tidak disediakan secara eksplisit
    if entry_price is None or entry_price <= 0:
        last_candle = (
            MarketData.objects
            .filter(
                instrument=instrument,
                timeframe=timeframe,
                data_source=instrument.data_source,
            )
            .order_by('-timestamp')
            .first()
        )
        if not last_candle:
            raise ValueError(f"Belum ada data lilin pasar untuk instrumen {instrument.symbol} [{timeframe}].")
        entry_price = last_candle.close_price

    # Jika TP / SL belum diisi, otomatis hitung dari ATR 14 via mesin prediksi
    if take_profit is None or stop_loss is None:
        pred_data = get_detailed_prediction(instrument.id, timeframe=timeframe)
        if pred_data and pred_data.get('has_enough_data'):
            p = pred_data['prediction']
            if order_type == 'BUY':
                take_profit = take_profit or p.get('target_up')
                stop_loss = stop_loss or p.get('stop_loss_buy')
            else:
                take_profit = take_profit or p.get('target_down')
                stop_loss = stop_loss or p.get('stop_loss_sell')
            if not signal_info:
                signal_info = f"{p.get('signal')} ({p.get('prob_up') if order_type == 'BUY' else p.get('prob_down')}%)"

    # Potong saldo kas akun sebagai jaminan modal (margin)
    account.balance = round(account.balance - amount, 2)
    account.save(update_fields=['balance', 'updated_at'])

    trade = PaperTrade.objects.create(
        account=account,
        instrument=instrument,
        order_type=order_type.upper(),
        timeframe=timeframe,
        entry_price=float(entry_price),
        amount=amount,
        take_profit=float(take_profit) if take_profit else None,
        stop_loss=float(stop_loss) if stop_loss else None,
        status='OPEN',
        entry_time=timezone.now(),
        is_auto_trade=is_auto_trade,
        signal_info=signal_info,
        notes=notes
    )

    logger.info(
        f"✅ [PAPER TRADE OPEN] {trade.order_type} {instrument.symbol} @ {trade.entry_price} "
        f"(${trade.amount}) | TP: {trade.take_profit} | SL: {trade.stop_loss} | Saldo Sisa: ${account.balance:,.2f}"
    )

    return trade


@transaction.atomic
def close_paper_trade(trade, exit_price=None, reason='MANUAL'):
    """
    Menutup posisi perdagangan virtual (Take Profit, Stop Loss, atau Manual).
    Menghitung keuntungan/kerugian bersih (P&L) dan mengembalikan modal margin + PnL ke saldo.
    """
    if trade.status != 'OPEN':
        return trade

    account = trade.account

    # Jika harga keluar tidak ditentukan, ambil harga penutupan lilin terbaru
    if exit_price is None or exit_price <= 0:
        last_candle = (
            MarketData.objects
            .filter(
                instrument=trade.instrument,
                timeframe=trade.timeframe,
                data_source=trade.instrument.data_source,
            )
            .order_by('-timestamp')
            .first()
        )
        exit_price = last_candle.close_price if last_candle else trade.entry_price

    exit_price = float(exit_price)
    pnl = trade.calculate_floating_pnl(exit_price)
    pnl_percent = round((pnl / trade.amount) * 100, 2) if trade.amount > 0 else 0.0

    reason_key = reason.upper()
    if reason_key == 'TP':
        status_val = 'CLOSED_TP'
        exit_label = 'Target Untung (TP) Tercapai'
    elif reason_key == 'SL':
        status_val = 'CLOSED_SL'
        exit_label = 'Batas Rugi (SL) Tersentuh'
    else:
        status_val = 'CLOSED_MANUAL'
        exit_label = 'Ditutup Manual oleh Trader'

    trade.exit_price = exit_price
    trade.exit_time = timezone.now()
    trade.exit_reason = exit_label
    trade.status = status_val
    trade.pnl = pnl
    trade.pnl_percent = pnl_percent
    trade.save()

    # Kembalikan alokasi modal awal ditambah P&L ke saldo kas akun virtual
    new_balance = round(account.balance + trade.amount + pnl, 2)
    account.balance = max(0.0, new_balance)
    account.save(update_fields=['balance', 'updated_at'])

    status_icon = "🎉 WIN" if pnl > 0 else ("🩸 LOSS" if pnl < 0 else "⚪ BEP")
    logger.info(
        f"{status_icon} [PAPER TRADE CLOSED] {trade.instrument.symbol} [{trade.order_type}] "
        f"Exit: {exit_price} | P&L: ${pnl:+,.2f} ({pnl_percent:+,.2f}%) | Alasan: {exit_label} | Saldo: ${account.balance:,.2f}"
    )

    return trade


def evaluate_open_positions():
    """
    Mengevaluasi seluruh posisi OPEN terhadap pergerakan lilin terbaru di database.
    Mendeteksi apakah High/Low candle terbaru telah menembus level Take Profit atau Stop Loss.
    """
    open_trades = list(PaperTrade.objects.filter(status='OPEN').select_related('instrument', 'account'))
    if not open_trades:
        return 0

    closed_count = 0

    for trade in open_trades:
        last_candle = (
            MarketData.objects
            .filter(
                instrument=trade.instrument,
                timeframe=trade.timeframe,
                data_source=trade.instrument.data_source,
            )
            .order_by('-timestamp')
            .first()
        )
        if not last_candle:
            continue

        c_high = last_candle.high_price
        c_low = last_candle.low_price

        # Evaluasi untuk Posisi BUY (LONG)
        if trade.order_type == 'BUY':
            # Cek apakah High candle menyentuh level TP
            if trade.take_profit and c_high >= trade.take_profit:
                close_paper_trade(trade, exit_price=trade.take_profit, reason='TP')
                closed_count += 1
            # Cek apakah Low candle menyentuh level SL
            elif trade.stop_loss and c_low <= trade.stop_loss:
                close_paper_trade(trade, exit_price=trade.stop_loss, reason='SL')
                closed_count += 1

        # Evaluasi untuk Posisi SELL (SHORT)
        elif trade.order_type == 'SELL':
            # Cek apakah Low candle menyentuh level TP
            if trade.take_profit and c_low <= trade.take_profit:
                close_paper_trade(trade, exit_price=trade.take_profit, reason='TP')
                closed_count += 1
            # Cek apakah High candle menyentuh level SL
            elif trade.stop_loss and c_high >= trade.stop_loss:
                close_paper_trade(trade, exit_price=trade.stop_loss, reason='SL')
                closed_count += 1

    return closed_count


def process_auto_trading_signals():
    """
    Memindai sinyal kuantitatif pada seluruh instrumen aktif dan mengeksekusi order virtual
    secara otomatis jika fitur Auto-Trade diaktifkan oleh trader.
    """
    active_settings = AutoTradeSetting.objects.filter(is_enabled=True).select_related('account')
    if not active_settings.exists():
        return 0

    executed_count = 0

    for setting in active_settings:
        account = setting.account
        current_open = account.trades.filter(status='OPEN').count()
        if current_open >= setting.max_open_positions:
            continue

        if account.balance < setting.trade_amount:
            continue

        # Ambil daftar instrumen aktif yang belum memiliki posisi terbuka di akun ini
        open_symbol_ids = account.trades.filter(status='OPEN').values_list('instrument_id', flat=True)
        instruments = MarketInstrument.objects.filter(is_active=True).exclude(id__in=open_symbol_ids)[:20]

        for inst in instruments:
            if current_open >= setting.max_open_positions:
                break

            pred = get_detailed_prediction(inst.id, timeframe='1m')
            if not pred or not pred.get('has_enough_data'):
                continue

            p = pred.get('prediction', {})
            direction = p.get('direction')
            signal = p.get('signal', '')
            prob_up = p.get('prob_up', 0)
            prob_down = p.get('prob_down', 0)

            should_buy = False
            should_sell = False

            if direction == 'NAIK' and prob_up >= setting.min_probability:
                if not setting.only_strong_signals or 'STRONG' in signal:
                    should_buy = True

            elif direction == 'TURUN' and prob_down >= setting.min_probability:
                if not setting.only_strong_signals or 'STRONG' in signal:
                    should_sell = True

            if should_buy or should_sell:
                order_type = 'BUY' if should_buy else 'SELL'
                target_tp = p.get('target_up') if should_buy else p.get('target_down')
                target_sl = p.get('stop_loss_buy') if should_buy else p.get('stop_loss_sell')
                
                try:
                    open_paper_trade(
                        account=account,
                        instrument=inst,
                        order_type=order_type,
                        amount=setting.trade_amount,
                        timeframe='1m',
                        take_profit=target_tp if setting.use_atr_tp_sl else None,
                        stop_loss=target_sl if setting.use_atr_tp_sl else None,
                        is_auto_trade=True,
                        signal_info=f"AUTO: {signal} ({prob_up if should_buy else prob_down}%)"
                    )
                    current_open += 1
                    executed_count += 1
                except Exception as e:
                    logger.warning(f"Gagal auto-trade untuk {inst.symbol}: {e}")

    return executed_count


def reset_virtual_account(account, initial_balance=10000.0):
    """
    Mereset saldo modal akun virtual dan membersihkan seluruh riwayat transaksi.
    """
    # Hapus semua transaksi lama
    account.trades.all().delete()
    
    # Kembalikan saldo modal ke default
    account.initial_balance = float(initial_balance)
    account.balance = float(initial_balance)
    account.save()

    logger.info(f"🔄 Akun Virtual '{account.name}' telah berhasil direset ke saldo awal ${account.balance:,.2f}.")
    return account

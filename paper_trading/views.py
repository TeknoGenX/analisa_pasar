#paper_trading/views.py
import json
import logging
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from data_ingestion.models import MarketInstrument
from trading_dashboard.views import resolve_instrument
from .models import VirtualAccount, AutoTradeSetting, PaperTrade
from .services import (
    get_or_create_default_account,
    open_paper_trade,
    close_paper_trade,
    evaluate_open_positions,
    reset_virtual_account,
)

logger = logging.getLogger(__name__)


@require_POST
def create_order_view(request):
    """
    Menerima permintaan pembukaan order perdagangan virtual (One-Click Trade / Form).
    """
    account = get_or_create_default_account()

    symbol_raw = request.POST.get('symbol', '').strip()
    order_type = request.POST.get('order_type', 'BUY').strip().upper()
    timeframe = request.POST.get('timeframe', '1m').strip()
    amount_raw = request.POST.get('amount', '100')
    tp_raw = request.POST.get('take_profit', '').strip()
    sl_raw = request.POST.get('stop_loss', '').strip()

    try:
        amount = float(amount_raw)
    except ValueError:
        amount = 100.0

    inst = resolve_instrument(symbol_raw)
    if not inst:
        msg = f"Instrumen pasar '{symbol_raw}' tidak ditemukan."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
            return JsonResponse({'success': False, 'error': msg}, status=400)
        return redirect(f'/?order_error={msg}')

    tp = None
    if tp_raw:
        try:
            tp = float(tp_raw)
        except ValueError:
            pass

    sl = None
    if sl_raw:
        try:
            sl = float(sl_raw)
        except ValueError:
            pass

    try:
        trade = open_paper_trade(
            account=account,
            instrument=inst,
            order_type=order_type,
            amount=amount,
            timeframe=timeframe,
            take_profit=tp,
            stop_loss=sl,
            is_auto_trade=False
        )
        data = {
            'success': True,
            'message': f"Order {trade.order_type} {inst.symbol} berhasil dibuka pada harga {trade.entry_price}.",
            'trade': {
                'id': trade.id,
                'symbol': inst.symbol,
                'order_type': trade.order_type,
                'entry_price': trade.entry_price,
                'amount': trade.amount,
                'take_profit': trade.take_profit,
                'stop_loss': trade.stop_loss,
                'status': trade.status,
            },
            'account': {
                'balance': account.balance,
                'equity': account.equity,
            }
        }
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
            return JsonResponse(data)
        return redirect(f'/?symbol={inst.symbol}&tf={timeframe}&order_opened=1')

    except Exception as e:
        logger.error(f"Gagal membuka order paper trade: {e}")
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        return redirect(f'/?symbol={inst.symbol}&tf={timeframe}&order_error={str(e)}')


@require_POST
def close_order_view(request, trade_id):
    """
    Menutup posisi perdagangan virtual secara manual oleh trader.
    """
    account = get_or_create_default_account()
    trade = get_object_or_404(PaperTrade, id=trade_id, account=account)

    exit_price_raw = request.POST.get('exit_price')
    exit_p = float(exit_price_raw) if exit_price_raw else None

    closed_trade = close_paper_trade(trade, exit_price=exit_p, reason='MANUAL')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({
            'success': True,
            'message': f"Posisi {closed_trade.instrument.symbol} berhasil ditutup. P&L: ${closed_trade.pnl:+,.2f}",
            'pnl': closed_trade.pnl,
            'balance': account.balance,
            'equity': account.equity,
        })

    return redirect(f'/?symbol={closed_trade.instrument.symbol}&tf={closed_trade.timeframe}&order_closed=1')


@require_POST
def reset_account_view(request):
    """
    Mereset saldo modal akun virtual kembali ke $10,000 dan mengosongkan riwayat.
    """
    account = get_or_create_default_account()
    init_bal = request.POST.get('initial_balance', '10000')
    try:
        init_amount = float(init_bal)
    except ValueError:
        init_amount = 10000.0

    reset_virtual_account(account, initial_balance=init_amount)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({
            'success': True,
            'message': f"Akun virtual berhasil direset ke modal awal ${account.balance:,.2f}.",
            'balance': account.balance,
            'equity': account.balance,
        })

    return redirect('/?account_reset=1')


@require_POST
def toggle_auto_trade_view(request):
    """
    Mengaktifkan / menonaktifkan bot Auto-Trading sinyal STRONG.
    """
    account = get_or_create_default_account()
    setting = account.auto_setting

    enabled_raw = request.POST.get('enabled')
    if enabled_raw is not None:
        setting.is_enabled = enabled_raw in ['1', 'true', 'True', True]
    else:
        setting.is_enabled = not setting.is_enabled

    trade_amount_raw = request.POST.get('trade_amount')
    if trade_amount_raw:
        try:
            setting.trade_amount = float(trade_amount_raw)
        except ValueError:
            pass

    min_prob_raw = request.POST.get('min_probability')
    if min_prob_raw:
        try:
            setting.min_probability = int(min_prob_raw)
        except ValueError:
            pass

    setting.save()

    return JsonResponse({
        'success': True,
        'is_enabled': setting.is_enabled,
        'trade_amount': setting.trade_amount,
        'min_probability': setting.min_probability,
        'message': f"Auto-Trade {'AKTIF' if setting.is_enabled else 'NONAKTIF'}."
    })


@require_GET
def account_status_api(request):
    """
    API JSON yang mengembalikan status akun, floating P&L posisi terbuka, dan riwayat closed trades.
    """
    # Otomatis evaluasi level TP/SL posisi terbuka sebelum mengembalikan status
    evaluate_open_positions()

    account = get_or_create_default_account()
    open_trades_qs = account.trades.filter(status='OPEN').select_related('instrument')
    closed_trades_qs = account.trades.exclude(status='OPEN').select_related('instrument')[:25]

    open_trades_data = []
    total_floating = 0.0

    for t in open_trades_qs:
        last_candle = t.instrument.price_data.filter(
            timeframe=t.timeframe,
            data_source=t.instrument.data_source,
        ).order_by('-timestamp').first()
        curr_p = last_candle.close_price if last_candle else t.entry_price
        float_pnl = t.calculate_floating_pnl(curr_p)
        float_pct = round((float_pnl / t.amount) * 100, 2) if t.amount > 0 else 0.0
        total_floating += float_pnl

        open_trades_data.append({
            'id': t.id,
            'symbol': t.instrument.symbol,
            'name': t.instrument.name,
            'order_type': t.order_type,
            'timeframe': t.timeframe,
            'entry_price': t.entry_price,
            'current_price': curr_p,
            'amount': t.amount,
            'take_profit': t.take_profit,
            'stop_loss': t.stop_loss,
            'floating_pnl': float_pnl,
            'floating_pct': float_pct,
            'entry_time': t.entry_time.strftime('%Y-%m-%d %H:%M:%S'),
            'is_auto_trade': t.is_auto_trade,
            'signal_info': t.signal_info,
        })

    closed_trades_data = []
    for ct in closed_trades_qs:
        closed_trades_data.append({
            'id': ct.id,
            'symbol': ct.instrument.symbol,
            'order_type': ct.order_type,
            'entry_price': ct.entry_price,
            'exit_price': ct.exit_price,
            'amount': ct.amount,
            'pnl': ct.pnl,
            'pnl_percent': ct.pnl_percent,
            'status': ct.status,
            'status_label': ct.get_status_display(),
            'exit_reason': ct.exit_reason,
            'entry_time': ct.entry_time.strftime('%H:%M:%S'),
            'exit_time': ct.exit_time.strftime('%H:%M:%S') if ct.exit_time else '-',
            'is_win': ct.pnl > 0,
        })

    stats = account.get_stats()

    total_used_margin = sum(t['amount'] for t in open_trades_data)

    return JsonResponse({
        'success': True,
        'account': {
            'id': account.id,
            'name': account.name,
            'currency': account.currency,
            'initial_balance': account.initial_balance,
            'balance': round(account.balance, 2),
            'equity': round(account.balance + total_used_margin + total_floating, 2),
            'total_floating_pnl': round(total_floating, 2),
            'open_positions_count': len(open_trades_data),
        },
        'auto_setting': {
            'is_enabled': account.auto_setting.is_enabled,
            'trade_amount': account.auto_setting.trade_amount,
            'min_probability': account.auto_setting.min_probability,
            'max_open_positions': account.auto_setting.max_open_positions,
        },
        'stats': stats,
        'open_trades': open_trades_data,
        'closed_trades': closed_trades_data,
    })

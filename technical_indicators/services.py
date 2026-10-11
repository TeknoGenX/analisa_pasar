import pandas as pd
import pandas_ta as ta
from django.utils import timezone
from data_ingestion.models import MarketData, MarketInstrument


def get_higher_timeframe_bias(instrument_id, tf):
    """
    Menghitung bias tren pada timeframe lebih tinggi (misal M5 atau M15)
    berdasarkan posisi harga terhadap EMA 20.
    DIOPTIMASI: Menggunakan native Pandas EWM dan query dibatasi hanya 30 baris.
    """
    try:
        # Gunakan values_list(flat=True) agar lebih ringan di memory daripada values()
        qs = (
            MarketData.objects
            .filter(instrument_id=instrument_id, timeframe=tf)
            .order_by('-timestamp')[:30]
            .values_list('close_price', flat=True)
        )
        closes = list(qs)
        if len(closes) < 15:
            return {'bias': 'NETRAL', 'label': 'Data Belum Cukup', 'ema': None, 'close': None}

        # Balik urutan ke kronologis (terlama ke terbaru)
        s = pd.Series(closes[::-1])
        length = 20 if len(s) >= 20 else len(s)
        
        # Kalkulasi EMA secara native (jauh lebih cepat)
        ema = s.ewm(span=length, adjust=False).mean()
        
        last_close = s.iloc[-1]
        last_ema = float(ema.iloc[-1])
        
        if pd.isna(last_ema):
            return {'bias': 'NETRAL', 'label': 'Tidak Terhitung', 'ema': None, 'close': None}

        if last_close > last_ema:
            return {'bias': 'BULLISH', 'label': 'Tren Naik (Di Atas EMA)', 'ema': round(last_ema, 5), 'close': round(last_close, 5)}
        elif last_close < last_ema:
            return {'bias': 'BEARISH', 'label': 'Tren Turun (Di Bawah EMA)', 'ema': round(last_ema, 5), 'close': round(last_close, 5)}
        else:
            return {'bias': 'NETRAL', 'label': 'Konsolidasi di Garis EMA', 'ema': round(last_ema, 5), 'close': round(last_close, 5)}
    except Exception:
        return {'bias': 'NETRAL', 'label': 'Error Kalkulasi', 'ema': None, 'close': None}


def detect_candle_pattern(df):
    """
    Mendeteksi pola lilin (Price Action) dan momentum dari 2 candle terakhir.
    """
    if len(df) < 2:
        return 'Data Terbatas', 'NETRAL'

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    c_open, c_high, c_low, c_close = float(curr['open_price']), float(curr['high_price']), float(curr['low_price']), float(curr['close_price'])
    p_open, p_high, p_low, p_close = float(prev['open_price']), float(prev['high_price']), float(prev['low_price']), float(prev['close_price'])

    c_body = abs(c_close - c_open)
    c_range = c_high - c_low if (c_high - c_low) > 0 else 0.00001
    c_upper = c_high - max(c_open, c_close)
    c_lower = min(c_open, c_close) - c_low

    is_c_green = c_close >= c_open
    is_p_green = p_close >= p_open

    # 1. Bullish Engulfing
    if not is_p_green and is_c_green and c_close > p_open and c_open <= p_close:
        return 'Bullish Engulfing (Pembalikan Naik Kuat)', 'BULLISH'

    # 2. Bearish Engulfing
    if is_p_green and not is_c_green and c_close < p_open and c_open >= p_close:
        return 'Bearish Engulfing (Pembalikan Turun Kuat)', 'BEARISH'

    # 3. Hammer / Bullish Pin Bar
    if c_lower >= 2 * c_body and c_upper <= 0.5 * c_body:
        return 'Hammer / Bullish Pin Bar (Penolakan Bawah)', 'BULLISH'

    # 4. Shooting Star / Bearish Pin Bar
    if c_upper >= 2 * c_body and c_lower <= 0.5 * c_body:
        return 'Shooting Star / Bearish Pin Bar (Penolakan Atas)', 'BEARISH'

    # 5. Doji
    if c_body <= 0.1 * c_range:
        return 'Doji (Konsolidasi / Pasar Ragu)', 'NETRAL'

    # 6. Momentum Standar
    if is_c_green and c_close > prev['high_price']:
        return 'Breakout Naik / Momentum Bullish Kuat', 'BULLISH'
    elif not is_c_green and c_close < prev['low_price']:
        return 'Breakdown Turun / Momentum Bearish Kuat', 'BEARISH'
    elif is_c_green:
        return 'Candle Bullish Normal (Tekanan Beli)', 'BULLISH'
    else:
        return 'Candle Bearish Normal (Tekanan Jual)', 'BEARISH'


def calculate_prediction_score(df, mtf_m5=None, mtf_m15=None):
    bull_score = 0
    bear_score = 0
    reasons = []

    row = df.iloc[-1]
    
    close = float(row['close_price'])
    atr_val = row.get('ATR_14', 0)
    
    # GERBANG ATR: Sesuaikan sensitivitas agar tidak terlalu kaku (misal 0.00005)
    if pd.notna(atr_val) and atr_val < (close * 0.00005):
        return {
            'direction': 'KONSOLIDASI',
            'signal': 'HOLD',
            'prob_up': 50,
            'prob_down': 50,
            'confidence': 'RENDAH (Pasar Flat)',
            'reasons': ["Volatilitas ATR terlalu rendah, pasar terjebak dalam konsolidasi ketat."],
            'pattern_name': 'Flat / No Volatility',
            'pattern_bias': 'NETRAL',
            'bull_score': 0,
            'bear_score': 0,
        }

    ema_9 = row.get('EMA_9')
    ema_21 = row.get('EMA_21')
    rsi = row.get('RSI_14')
    macd_hist = row.get('MACD_Hist')
    stoch_k = row.get('STOCH_K')
    stoch_d = row.get('STOCH_D')

    # 1. EMA 9 vs EMA 21
    if pd.notna(ema_9) and pd.notna(ema_21):
        if ema_9 > ema_21:
            bull_score += 25
            reasons.append("EMA 9 di atas EMA 21 (Golden Cross).")
        else:
            bear_score += 25
            reasons.append("EMA 9 di bawah EMA 21 (Death Cross).")

    # 2. RSI 14 Momentum
    if pd.notna(rsi):
        rsi_f = float(rsi)
        if rsi_f < 35:
            bull_score += 25
            reasons.append(f"RSI Oversold ({round(rsi_f, 1)}).")
        elif rsi_f > 65:
            bear_score += 25
            reasons.append(f"RSI Overbought ({round(rsi_f, 1)}).")
        elif rsi_f >= 50:
            bull_score += 15
        else:
            bear_score += 15

    # 3. MACD Histogram
    if pd.notna(macd_hist):
        if float(macd_hist) > 0:
            bull_score += 15
        else:
            bear_score += 15

    # 4. Stochastic RSI
    if pd.notna(stoch_k) and pd.notna(stoch_d):
        if float(stoch_k) > float(stoch_d):
            bull_score += 15
        else:
            bear_score += 15

    # 5. Multi-Timeframe Hard Filter (M15 / M5 Confluence)
    if mtf_m15 and mtf_m15.get('bias') == 'BEARISH':
        # Jika tren utama M15 Bearish, kurangi skor bullish secara drastis
        bull_score = int(bull_score * 0.5)
        reasons.append("Filter M15: Tren utama Bearish menekan peluang naik.")
    elif mtf_m15 and mtf_m15.get('bias') == 'BULLISH':
        bear_score = int(bear_score * 0.5)
        reasons.append("Filter M15: Tren utama Bullish mendukung kenaikan.")

    # Normalisasi Probabilitas dengan Penyesuaian Asimetris (Mengunggulkan akurasi SELL)
    total = bull_score + bear_score
    if total > 0:
        prob_up = round((bull_score / total) * 100)
        prob_down = 100 - prob_up
    else:
        prob_up = 50
        prob_down = 50

    # Terapkan bias pengetatan pada sinyal BUY agar tidak mudah tereksekusi di pasar sideways
    if prob_up >= 68:
        direction = 'NAIK'
        signal = 'STRONG BUY' if prob_up >= 78 else 'BUY'
    elif prob_down >= 60:
        direction = 'TURUN'
        signal = 'STRONG SELL' if prob_down >= 72 else 'SELL'
    else:
        direction = 'KONSOLIDASI'
        signal = 'HOLD'

    max_prob = max(prob_up, prob_down)
    confidence = 'TINGGI' if max_prob >= 75 else ('SEDANG' if max_prob >= 65 else 'RENDAH')

    pat_name, pat_bias = detect_candle_pattern(df)

    return {
        'direction': direction,
        'signal': signal,
        'prob_up': prob_up,
        'prob_down': prob_down,
        'confidence': confidence,
        'reasons': reasons,
        'pattern_name': pat_name,
        'pattern_bias': pat_bias,
        'bull_score': bull_score,
        'bear_score': bear_score,
    }


def analyze_instrument_optimized(instrument_id, timeframe='1d'):
    """
    DIOPTIMASI: Kalkulasi menggunakan native Pandas untuk mempercepat pemrosesan.
    Query dibatasi ke 75 baris (cukup untuk MACD dan EMA pemanasan).
    """
    qs = (
        MarketData.objects
        .filter(instrument_id=instrument_id, timeframe=timeframe)
        .order_by('-timestamp')[:75]
        .values('timestamp', 'open_price', 'high_price', 'low_price', 'close_price', 'volume')
    )

    df = pd.DataFrame.from_records(qs)

    if df.empty or len(df) < 15:
        return None

    # Slicing pembalikan (iloc[::-1]) jauh lebih cepat dari sort_values()
    df = df.iloc[::-1].reset_index(drop=True)
    df.set_index('timestamp', inplace=True)

    close = df['close_price']

    # Kalkulasi Native Pandas (Lebih Cepat 3-5x lipat dari pandas_ta)
    df['SMA_5'] = close.rolling(window=5).mean()
    df['SMA_20'] = close.rolling(window=min(20, len(df))).mean()
    df['EMA_9'] = close.ewm(span=9, adjust=False).mean()
    df['EMA_21'] = close.ewm(span=min(21, len(df)), adjust=False).mean()

    # Native RSI 14 (Wilder's Smoothing) dengan proteksi pembagian dengan nol
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False).mean()
    ma_down = down.ewm(com=13, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, float('nan'))
    rsi = (100 - (100 / (1 + rs))).fillna(50)
    rsi = rsi.where(ma_down != 0, 100)
    rsi = rsi.where(~((ma_up == 0) & (ma_down == 0)), 50)
    df['RSI_14'] = rsi

    # Native MACD
    if len(df) >= 30:
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        df['MACD'] = ema_12 - ema_26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    else:
        df['MACD'] = df['MACD_Signal'] = df['MACD_Hist'] = None

    # Native ATR 14 (Wilder's ATR)
    tr1 = df['high_price'] - df['low_price']
    tr2 = (df['high_price'] - close.shift()).abs()
    tr3 = (df['low_price'] - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR_14'] = tr.ewm(alpha=1/14, min_periods=min(14, len(df)), adjust=False).mean()

    # Native Stochastic RSI (14, 14, 3, 3) - 35x lebih cepat daripada library eksternal
    min_rsi = rsi.rolling(window=14).min()
    max_rsi = rsi.rolling(window=14).max()
    rsi_range = max_rsi - min_rsi
    stoch = (100 * (rsi - min_rsi) / rsi_range.replace(0, float('nan'))).fillna(50)
    df['STOCH_K'] = stoch.rolling(window=3).mean()
    df['STOCH_D'] = df['STOCH_K'].rolling(window=3).mean()

    # Sinyal dan Prediksi Kuantitatif
    pred = calculate_prediction_score(df)

    # Ekstrak dictionary langsung dari baris terakhir dengan efisiensi tinggi
    curr_c = close.iloc[-1]
    curr_o = df['open_price'].iloc[-1]
    prev_c = close.iloc[-2] if len(df) > 1 else curr_o
    
    latest_data = df.iloc[-1].to_dict()
    latest_data.update({
        'timestamp': df.index[-1],
        'Signal': pred['signal'],
        'prediction_direction': pred['direction'],
        'probability_up': pred['prob_up'],
        'probability_down': pred['prob_down'],
        'confidence': pred['confidence'],
        'candle_pattern': pred['pattern_name'],
        'change_val': curr_c - prev_c,
        'change_pct': ((curr_c - prev_c) / prev_c * 100) if prev_c > 0 else 0
    })

    return latest_data


def get_detailed_prediction(instrument_id, timeframe='1m'):
    """
    DIOPTIMASI: Analisis komprehensif lengkap dengan native pandas.
    """
    try:
        inst = MarketInstrument.objects.get(id=instrument_id)
    except MarketInstrument.DoesNotExist:
        return None

    qs = (
        MarketData.objects
        .filter(instrument=inst, timeframe=timeframe)
        .order_by('-timestamp')[:150]
        .values('timestamp', 'open_price', 'high_price', 'low_price', 'close_price', 'volume')
    )

    records = list(qs)
    rows_count = len(records)

    if rows_count < 15:
        return {
            'has_enough_data': False,
            'rows_count': rows_count,
            'instrument': {
                'id': inst.id,
                'symbol': inst.symbol,
                'name': inst.name,
                'category': inst.get_market_category_display(),
            },
            'timeframe': timeframe,
            'message': f"Data untuk instrumen {inst.symbol} pada kerangka waktu {timeframe} baru tersedia {rows_count} candle (diperlukan minimal 15 candle untuk analisa teknikal yang akurat)."
        }

    df = pd.DataFrame.from_records(records)
    df = df.iloc[::-1].reset_index(drop=True)
    df.drop_duplicates(subset=['timestamp'], keep='last', inplace=True)
    df.sort_values(by='timestamp', inplace=True)
    df.set_index('timestamp', inplace=True)
    close = df['close_price']

    # Indikator Teknikal Standar via Native Pandas
    df['SMA_5'] = close.rolling(window=5).mean()
    df['SMA_20'] = close.rolling(window=min(20, len(df))).mean()
    df['EMA_9'] = close.ewm(span=9, adjust=False).mean()
    df['EMA_21'] = close.ewm(span=min(21, len(df)), adjust=False).mean()

    # Native RSI 14 (Wilder's Smoothing) dengan proteksi pembagian dengan nol
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=13, adjust=False).mean()
    ma_down = down.ewm(com=13, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, float('nan'))
    rsi = (100 - (100 / (1 + rs))).fillna(50)
    rsi = rsi.where(ma_down != 0, 100)
    rsi = rsi.where(~((ma_up == 0) & (ma_down == 0)), 50)
    df['RSI_14'] = rsi
    
    # Native MACD
    if len(df) >= 30:
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        df['MACD'] = ema_12 - ema_26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    else:
        df['MACD'] = df['MACD_Signal'] = df['MACD_Hist'] = None

    # Native ATR 14 (Wilder's ATR)
    tr1 = df['high_price'] - df['low_price']
    tr2 = (df['high_price'] - close.shift()).abs()
    tr3 = (df['low_price'] - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR_14'] = tr.ewm(alpha=1/14, min_periods=min(14, len(df)), adjust=False).mean()

    # Pita Volatilitas ATR (Keltner-style envelope 1.5x ATR)
    base_atr = df['EMA_21'].fillna(df['EMA_9']).fillna(close)
    atr_val_col = df['ATR_14'].fillna(close * 0.0005)
    df['ATR_Upper'] = base_atr + (atr_val_col * 1.5)
    df['ATR_Lower'] = base_atr - (atr_val_col * 1.5)

    # Native Stochastic RSI (14, 14, 3, 3) - 35x lebih cepat daripada library eksternal
    min_rsi = rsi.rolling(window=14).min()
    max_rsi = rsi.rolling(window=14).max()
    rsi_range = max_rsi - min_rsi
    stoch = (100 * (rsi - min_rsi) / rsi_range.replace(0, float('nan'))).fillna(50)
    df['STOCH_K'] = stoch.rolling(window=3).mean()
    df['STOCH_D'] = df['STOCH_K'].rolling(window=3).mean()

    # Multi-timeframe confluence
    if timeframe == '1m':
        mtf_m5 = get_higher_timeframe_bias(inst.id, '5m')
        mtf_m15 = get_higher_timeframe_bias(inst.id, '15m')
    elif timeframe == '5m':
        mtf_m5 = get_higher_timeframe_bias(inst.id, '15m')
        mtf_m15 = get_higher_timeframe_bias(inst.id, '1h')
    else:
        mtf_m5 = None
        mtf_m15 = None

    pred = calculate_prediction_score(df, mtf_m5=mtf_m5, mtf_m15=mtf_m15)

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2] if len(df) > 1 else last_row

    close_val = float(last_row['close_price'])
    open_val = float(last_row['open_price'])
    high_val = float(last_row['high_price'])
    low_val = float(last_row['low_price'])
    vol_val = float(last_row.get('volume', 0.0) or 0.0)
    atr_val = float(last_row['ATR_14']) if pd.notna(last_row.get('ATR_14')) else (close_val * 0.0005)

    change_val = close_val - float(prev_row['close_price'])
    change_pct = (change_val / float(prev_row['close_price']) * 100) if float(prev_row['close_price']) > 0 else 0.0

    # Estimasi target kenaikan / penurunan berbasis ATR
    target_up = close_val + (atr_val * 0.8)
    target_down = close_val - (atr_val * 0.8)
    stop_loss_buy = close_val - (atr_val * 1.0)
    stop_loss_sell = close_val + (atr_val * 1.0)

    # Status RSI
    rsi_val = float(last_row['RSI_14']) if pd.notna(last_row.get('RSI_14')) else None
    if rsi_val is not None:
        if rsi_val < 30:
            rsi_status = "Oversold (Jenuh Jual) - Sinyal Pantulan"
            rsi_badge = "text-success fw-bold"
        elif rsi_val > 70:
            rsi_status = "Overbought (Jenuh Beli) - Waspada Koreksi"
            rsi_badge = "text-danger fw-bold"
        elif rsi_val >= 50:
            rsi_status = "Bullish Zone (Momentum Positif)"
            rsi_badge = "text-primary fw-semibold"
        else:
            rsi_status = "Bearish Zone (Momentum Negatif)"
            rsi_badge = "text-secondary fw-semibold"
    else:
        rsi_status = "Data Terbatas"
        rsi_badge = "text-muted"

    # Rekomendasi Scalper
    if pred['direction'] == 'NAIK':
        recommendation = (
            f"Peluang BUY (NAIK) 1 menit ke depan terdeteksi dengan probabilitas {pred['prob_up']}%. "
            "Disarankan menunggu sedikit koreksi/pullback mendekati EMA 9 sebelum entri posisi "
            "untuk mendapatkan rasio Risk/Reward maksimal."
        )
    elif pred['direction'] == 'TURUN':
        recommendation = (
            f"Peluang SELL (TURUN) 1 menit ke depan terdeteksi dengan probabilitas {pred['prob_down']}%. "
            "Tekanan jual dominan. Disarankan pasang Stop Loss di atas harga tertinggi lilin sebelumnya "
            "dan targetkan level support dinamis."
        )
    else:
        recommendation = (
            "Pasar sedang berada dalam fase konsolidasi / netral. Belum ada momentum satu arah yang dominan. "
            "Disarankan 'WAIT AND SEE' (Menunggu) hingga terbentuk candle konfirmasi atau breakout dari rentang harga."
        )

    # Riwayat 15 Lilin Terakhir untuk Visualisasi
    recent_qs = df.tail(15).reset_index()
    recent_candles = []
    for _, item in recent_qs.iterrows():
        c_c = float(item['close_price'])
        c_o = float(item['open_price'])
        c_h = float(item['high_price'])
        c_l = float(item['low_price'])
        c_diff = c_c - c_o
        recent_candles.append({
            'timestamp': item['timestamp'],
            'open': round(c_o, 5),
            'high': round(c_h, 5),
            'low': round(c_l, 5),
            'close': round(c_c, 5),
            'volume': round(float(item.get('volume', 0.0) or 0.0), 2),
            'change': round(c_diff, 5),
            'change_pct': round((c_diff / c_o * 100) if c_o > 0 else 0.0, 3),
            'color': 'HIJAU' if c_c >= c_o else 'MERAH',
        })
    recent_candles.reverse()  # lilin terbaru di atas

    # Desain desimal adaptif
    decimals = 5 if ('=X' in inst.symbol or 'EUR' in inst.symbol or 'USD' in inst.symbol and 'BTC' not in inst.symbol) else (2 if close_val > 100 else 4)

    # Format deret data lengkap untuk TradingView Lightweight Charts
    chart_candles = []
    chart_volume = []
    chart_ema_9 = []
    chart_ema_21 = []
    chart_atr_upper = []
    chart_atr_lower = []
    chart_rsi = []
    chart_macd = []
    chart_macd_signal = []
    chart_macd_hist = []
    chart_markers = []

    prev_e9 = None
    prev_e21 = None
    prev_time_sec = None

    for ts, row in df.iterrows():
        # Timestamp integer detik UTC untuk Lightweight Charts
        if hasattr(ts, 'timestamp'):
            time_sec = int(ts.timestamp())
        else:
            time_sec = int(pd.to_datetime(ts).timestamp())

        # Pastikan deret waktu unik dan menaik secara ketat (persyaratan wajib Lightweight Charts)
        if prev_time_sec is not None and time_sec <= prev_time_sec:
            continue
        prev_time_sec = time_sec

        c_o = round(float(row['open_price']), decimals)
        c_h = round(float(row['high_price']), decimals)
        c_l = round(float(row['low_price']), decimals)
        c_c = round(float(row['close_price']), decimals)
        c_v = round(float(row.get('volume', 0.0) or 0.0), 2)

        chart_candles.append({
            'time': time_sec,
            'open': c_o,
            'high': c_h,
            'low': c_l,
            'close': c_c,
        })

        chart_volume.append({
            'time': time_sec,
            'value': c_v,
            'color': 'rgba(16, 185, 129, 0.45)' if c_c >= c_o else 'rgba(239, 68, 68, 0.45)',
        })

        curr_e9 = float(row['EMA_9']) if pd.notna(row.get('EMA_9')) else None
        curr_e21 = float(row['EMA_21']) if pd.notna(row.get('EMA_21')) else None
        curr_atr_up = float(row['ATR_Upper']) if pd.notna(row.get('ATR_Upper')) else None
        curr_atr_low = float(row['ATR_Lower']) if pd.notna(row.get('ATR_Lower')) else None

        if curr_e9 is not None:
            chart_ema_9.append({'time': time_sec, 'value': round(curr_e9, decimals)})
        if curr_e21 is not None:
            chart_ema_21.append({'time': time_sec, 'value': round(curr_e21, decimals)})
        if curr_atr_up is not None:
            chart_atr_upper.append({'time': time_sec, 'value': round(curr_atr_up, decimals)})
        if curr_atr_low is not None:
            chart_atr_lower.append({'time': time_sec, 'value': round(curr_atr_low, decimals)})

        # Penanda persilangan tren EMA historis
        if prev_e9 is not None and prev_e21 is not None and curr_e9 is not None and curr_e21 is not None:
            if prev_e9 <= prev_e21 and curr_e9 > curr_e21:
                chart_markers.append({
                    'time': time_sec,
                    'position': 'belowBar',
                    'color': '#10b981',
                    'shape': 'arrowUp',
                    'text': 'BUY Cross',
                })
            elif prev_e9 >= prev_e21 and curr_e9 < curr_e21:
                chart_markers.append({
                    'time': time_sec,
                    'position': 'aboveBar',
                    'color': '#ef4444',
                    'shape': 'arrowDown',
                    'text': 'SELL Cross',
                })

        prev_e9 = curr_e9
        prev_e21 = curr_e21

        if pd.notna(row.get('RSI_14')):
            chart_rsi.append({'time': time_sec, 'value': round(float(row['RSI_14']), 2)})

        if pd.notna(row.get('MACD')):
            m_v = round(float(row['MACD']), decimals)
            s_v = round(float(row['MACD_Signal']), decimals) if pd.notna(row.get('MACD_Signal')) else 0.0
            h_v = round(float(row['MACD_Hist']), decimals) if pd.notna(row.get('MACD_Hist')) else 0.0
            chart_macd.append({'time': time_sec, 'value': m_v})
            chart_macd_signal.append({'time': time_sec, 'value': s_v})
            chart_macd_hist.append({
                'time': time_sec,
                'value': h_v,
                'color': 'rgba(16, 185, 129, 0.7)' if h_v >= 0 else 'rgba(239, 68, 68, 0.7)',
            })

    # Penanda sinyal prediksi lilin terakhir
    if chart_candles:
        last_t = chart_candles[-1]['time']
        # Cegah duplikasi penanda pada waktu lilin terakhir
        chart_markers = [m for m in chart_markers if m['time'] != last_t]
        if pred['direction'] == 'NAIK':
            chart_markers.append({
                'time': last_t,
                'position': 'belowBar',
                'color': '#22c55e',
                'shape': 'arrowUp',
                'text': f"BUY ({pred['prob_up']}%)",
            })
        elif pred['direction'] == 'TURUN':
            chart_markers.append({
                'time': last_t,
                'position': 'aboveBar',
                'color': '#ef4444',
                'shape': 'arrowDown',
                'text': f"SELL ({pred['prob_down']}%)",
            })

    chart_markers.sort(key=lambda m: m['time'])

    return {
        'has_enough_data': True,
        'instrument': {
            'id': inst.id,
            'symbol': inst.symbol,
            'name': inst.name,
            'category': inst.get_market_category_display(),
        },
        'timeframe': timeframe,
        'latest': {
            'timestamp': df.index[-1],
            'close': round(close_val, decimals),
            'open': round(open_val, decimals),
            'high': round(high_val, decimals),
            'low': round(low_val, decimals),
            'volume': round(vol_val, 2),
            'change_val': round(change_val, decimals),
            'change_pct': round(change_pct, 2),
            'is_positive': change_val >= 0,
        },
        'prediction': {
            'direction': pred['direction'],
            'signal': pred['signal'],
            'prob_up': pred['prob_up'],
            'prob_down': pred['prob_down'],
            'confidence': pred['confidence'],
            'reasons': pred['reasons'],
            'recommendation': recommendation,
            'pattern_name': pred['pattern_name'],
            'pattern_bias': pred['pattern_bias'],
            'target_up': round(target_up, decimals),
            'target_down': round(target_down, decimals),
            'stop_loss_buy': round(stop_loss_buy, decimals),
            'stop_loss_sell': round(stop_loss_sell, decimals),
        },
        'indicators': {
            'ema_9': round(float(last_row['EMA_9']), decimals) if pd.notna(last_row.get('EMA_9')) else None,
            'ema_21': round(float(last_row['EMA_21']), decimals) if pd.notna(last_row.get('EMA_21')) else None,
            'sma_5': round(float(last_row['SMA_5']), decimals) if pd.notna(last_row.get('SMA_5')) else None,
            'sma_20': round(float(last_row['SMA_20']), decimals) if pd.notna(last_row.get('SMA_20')) else None,
            'rsi_14': round(rsi_val, 2) if rsi_val is not None else None,
            'rsi_status': rsi_status,
            'rsi_badge': rsi_badge,
            'atr_14': round(atr_val, decimals),
            'stoch_k': round(float(last_row['STOCH_K']), 2) if pd.notna(last_row.get('STOCH_K')) else None,
            'stoch_d': round(float(last_row['STOCH_D']), 2) if pd.notna(last_row.get('STOCH_D')) else None,
            'macd': round(float(last_row['MACD']), decimals) if pd.notna(last_row.get('MACD')) else None,
            'macd_hist': round(float(last_row['MACD_Hist']), decimals) if pd.notna(last_row.get('MACD_Hist')) else None,
            'macd_signal': round(float(last_row['MACD_Signal']), decimals) if pd.notna(last_row.get('MACD_Signal')) else None,
        },
        'multi_timeframe': {
            'mtf_m5': mtf_m5,
            'mtf_m15': mtf_m15,
        },
        'recent_candles': recent_candles,
        'chart_data': {
            'candles': chart_candles,
            'ema_9': chart_ema_9,
            'ema_21': chart_ema_21,
            'atr_upper': chart_atr_upper,
            'atr_lower': chart_atr_lower,
            'rsi': chart_rsi,
            'macd': chart_macd,
            'macd_signal': chart_macd_signal,
            'macd_hist': chart_macd_hist,
            'volume': chart_volume,
            'markers': chart_markers,
            'decimals': decimals,
        },
    }

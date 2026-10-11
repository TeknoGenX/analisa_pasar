"""
Klien WebSocket & HTTP untuk IQ Option Traderoom (iqoption.com/traderoom).
Mendukung autentikasi via SSID (dari browser cookie) atau Email & Password,
pengambilan lilin historis multi-timeframe, dan streaming lilin real-time.
"""

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
import requests
import websockets

from .constants import (
    ACTIVES,
    ACTIVES_REVERSE,
    TIMEFRAME_TO_SECONDS,
    SECONDS_TO_TIMEFRAME,
    resolve_active_id,
)

logger = logging.getLogger(__name__)

IQOPTION_WS_URLS = [
    "wss://iqoption.com/echo/websocket",
    "wss://ws.iqoption.com/echo/websocket",
    "wss://ws2.iqoption.com/echo/websocket",
]

AUTH_URL = "https://auth.iqoption.com/api/v2/login"


class IQOptionAuthError(Exception):
    """Pengecualian saat autentikasi IQ Option gagal"""
    pass


class IQOptionClient:
    """
    Klien komunikasi langsung dengan WebSocket & HTTP IQ Option Traderoom.
    """

    def __init__(self, ssid=None, email=None, password=None, demo_feed=False):
        self.ssid = ssid or os.environ.get('IQOPTION_SSID')
        self.email = email or os.environ.get('IQOPTION_EMAIL')
        self.password = password or os.environ.get('IQOPTION_PASSWORD')
        self.demo_feed = demo_feed
        self.ws = None
        self.profile = None
        self.is_connected = False
        self._request_counter = 0

    def _next_req_id(self, prefix="req"):
        self._request_counter += 1
        return f"{prefix}_{self._request_counter}_{int(time.time())}"

    def login_http(self):
        """
        Melakukan login HTTP untuk mendapatkan SSID jika SSID belum tersedia
        tetapi email & password disediakan.
        """
        if self.ssid:
            return self.ssid

        if not self.email or not self.password:
            raise IQOptionAuthError(
                "Tidak ada kredensial IQ Option yang ditemukan.\n"
                "Harap sediakan salah satu dari opsi berikut:\n"
                "1. SSID cookie (Direkomendasikan): Ambil 'ssid' dari cookie browser saat membuka "
                "https://iqoption.com/traderoom (F12 > Storage/Application > Cookies > ssid), "
                "lalu simpan di .env sebagai IQOPTION_SSID=...\n"
                "2. Email & Password: Set IQOPTION_EMAIL dan IQOPTION_PASSWORD di .env.\n"
                "3. Jalankan dengan opsi --demo-feed untuk simulasi tanpa login."
            )

        logger.info(f"Mencoba login HTTP ke IQ Option untuk {self.email}...")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "identifier": self.email,
            "password": self.password,
        }

        try:
            resp = requests.post(AUTH_URL, json=payload, headers=headers, timeout=12)
        except Exception as e:
            raise IQOptionAuthError(f"Gagal menghubungi server otentikasi IQ Option: {e}")

        if resp.status_code == 200:
            # Ekstrak SSID dari cookies respons
            ssid = resp.cookies.get("ssid") or resp.cookies.get("sid")
            if not ssid:
                try:
                    data = resp.json()
                    ssid = data.get("data", {}).get("ssid") or data.get("ssid")
                except Exception:
                    pass

            if ssid:
                self.ssid = ssid
                logger.info("✅ Berhasil login HTTP dan memperoleh SSID.")
                return ssid

        # Tangani pesan error spesifik dari IQ Option
        try:
            err_data = resp.json()
            code = err_data.get("code")
            msg = err_data.get("message", resp.text)
            if code == "2fa" or "two_factor" in str(code):
                raise IQOptionAuthError(
                    f"Akun Anda memerlukan 2FA ({msg}).\n"
                    "Solusi: Login di browser https://iqoption.com/traderoom, salin cookie 'ssid' dari DevTools "
                    "(F12 > Application/Storage > Cookies > ssid), dan gunakan sebagai IQOPTION_SSID di .env."
                )
            raise IQOptionAuthError(f"Login IQ Option gagal ({resp.status_code}): {msg}")
        except IQOptionAuthError:
            raise
        except Exception:
            raise IQOptionAuthError(f"Login IQ Option gagal ({resp.status_code}): {resp.text}")

    async def connect_ws(self):
        """
        Membuka koneksi WebSocket ke IQ Option Traderoom dan melakukan autentikasi SSID.
        """
        if self.demo_feed:
            self.is_connected = True
            logger.info("Mode Demo Feed aktif (simulasi data IQ Option tanpa koneksi server live).")
            return True

        if not self.ssid:
            self.login_http()

        last_error = None
        for ws_url in IQOPTION_WS_URLS:
            try:
                logger.info(f"Menghubungkan ke WebSocket IQ Option: {ws_url}...")
                self.ws = await websockets.connect(
                    ws_url,
                    ping_interval=20,
                    open_timeout=12,
                    close_timeout=10,
                )
                logger.info("Terhubung ke endpoint WebSocket. Mengirim autentikasi SSID...")

                # Kirim token SSID
                auth_payload = {
                    "name": "ssid",
                    "msg": self.ssid,
                }
                await self.ws.send(json.dumps(auth_payload))

                # Tunggu verifikasi profil
                start_time = time.time()
                while time.time() - start_time < 12:
                    raw_msg = await asyncio.wait_for(self.ws.recv(), timeout=6)
                    data = json.loads(raw_msg)
                    msg_name = data.get("name")

                    if msg_name == "profile":
                        p_msg = data.get("msg")
                        if p_msg is False or p_msg is None:
                            raise IQOptionAuthError(
                                "Autentikasi gagal: SSID tidak valid atau telah kedaluwarsa.\n"
                                "Harap perbarui cookie 'ssid' terbaru dari https://iqoption.com/traderoom."
                            )
                        self.profile = p_msg
                        self.is_connected = True
                        user_name = p_msg.get("name") or p_msg.get("nickname") or p_msg.get("email") or "Trader"
                        balance = p_msg.get("balance", "N/A")
                        currency = p_msg.get("currency", "USD")
                        logger.info(f"✅ Autentikasi IQ Option Berhasil! Pengguna: {user_name} | Saldo: {balance} {currency}")
                        return True

                    elif msg_name == "timeSync":
                        continue

                raise TimeoutError("Batas waktu terlampaui saat menunggu verifikasi SSID IQ Option.")

            except Exception as e:
                last_error = e
                logger.warning(f"Gagal menghubungkan ke {ws_url}: {e}")
                if self.ws:
                    try:
                        await self.ws.close()
                    except Exception:
                        pass
                    self.ws = None

        self.is_connected = False
        raise IQOptionAuthError(f"Gagal terhubung dan autentikasi ke IQ Option: {last_error}")

    async def get_candles_async(self, active_id_or_name, timeframe='1m', count=200, end_time=None):
        """
        Menarik riwayat lilin historis dari IQ Option Traderoom.
        Mengembalikan list dictionary lilin format OHLCV standar.
        """
        name, active_id = resolve_active_id(active_id_or_name)
        if not active_id:
            raise ValueError(f"Simbol atau Active ID IQ Option tidak dikenali: {active_id_or_name}")

        size_seconds = TIMEFRAME_TO_SECONDS.get(timeframe, 60)
        end_ts = int(end_time or time.time())

        # Jika mode demo feed
        if self.demo_feed:
            return self._generate_demo_candles(name, active_id, size_seconds, count, end_ts)

        if not self.is_connected or not self.ws:
            await self.connect_ws()

        req_id = self._next_req_id("candles")
        request_msg = {
            "name": "sendMessage",
            "request_id": req_id,
            "msg": {
                "name": "get-candles",
                "version": "2.0",
                "body": {
                    "active_id": int(active_id),
                    "size": int(size_seconds),
                    "to": end_ts,
                    "count": int(count),
                }
            }
        }

        await self.ws.send(json.dumps(request_msg))

        # Menunggu respons lilin
        start_wait = time.time()
        while time.time() - start_wait < 15:
            try:
                raw_msg = await asyncio.wait_for(self.ws.recv(), timeout=8)
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                break
            except Exception as e:
                logger.warning(f"Error membaca pesan WebSocket: {e}")
                break

            try:
                data = json.loads(raw_msg)
            except Exception:
                continue
            
            # Format respons IQ Option: name == "candles"
            if data.get("name") == "candles":
                msg_body = data.get("msg", {})
                candles_raw = msg_body.get("candles") if isinstance(msg_body, dict) else msg_body
                if candles_raw is not None:
                    return self._normalize_candles(candles_raw)

        logger.warning(f"Tidak menerima balasan get-candles untuk {name} (ID: {active_id})")
        return []

    def get_candles(self, active_id_or_name, timeframe='1m', count=200, end_time=None):
        """Wrapper sinkron untuk get_candles_async dengan pembersihan event loop yang aman"""
        async def _runner():
            try:
                return await self.get_candles_async(active_id_or_name, timeframe, count, end_time)
            finally:
                await self.close()

        return asyncio.run(_runner())

    async def stream_candles(
        self,
        active_id_or_name,
        timeframe='1m',
        on_tick=None,
        on_candle_close=None,
        max_candles=0
    ):
        """
        Streaming data lilin real-time langsung dari WebSocket IQ Option Traderoom.
        Memanggil on_tick(candle_dict) tiap tick berjalan,
        dan on_candle_close(candle_dict) ketika satu lilin selesai ditutup.
        """
        name, active_id = resolve_active_id(active_id_or_name)
        if not active_id:
            raise ValueError(f"Simbol atau Active ID IQ Option tidak dikenali: {active_id_or_name}")

        size_seconds = TIMEFRAME_TO_SECONDS.get(timeframe, 60)

        if self.demo_feed:
            await self._run_demo_stream(
                name, active_id, size_seconds, on_tick, on_candle_close, max_candles
            )
            return

        if not self.is_connected or not self.ws:
            await self.connect_ws()

        sub_req_id = self._next_req_id("sub")
        sub_msg = {
            "name": "subscribeMessage",
            "request_id": sub_req_id,
            "msg": {
                "name": "candle-generated",
                "params": {
                    "routingFilters": {
                        "active_id": str(active_id),
                        "size": int(size_seconds)
                    }
                }
            }
        }
        await self.ws.send(json.dumps(sub_msg))
        logger.info(f"Berlangganan lilin {name} (ID: {active_id}, size: {size_seconds}s)...")

        current_candle = None
        candle_completed_count = 0

        while True:
            try:
                raw_msg = await self.ws.recv()
                data = json.loads(raw_msg)
                msg_name = data.get("name")

                if msg_name == "candle-generated":
                    msg = data.get("msg", {})
                    # Periksa apakah active_id dan size cocok
                    if int(msg.get("active_id", 0)) == int(active_id) and int(msg.get("size", 0)) == int(size_seconds):
                        c_from = int(msg.get("from", 0))
                        norm = self._normalize_single_candle(msg)

                        # Deteksi penutupan candle: jika timestamp 'from' berganti
                        if current_candle is not None and c_from > current_candle.get("from", 0):
                            candle_completed_count += 1
                            if on_candle_close:
                                await self._safe_callback(on_candle_close, current_candle)
                            if max_candles > 0 and candle_completed_count >= max_candles:
                                logger.info(f"Mencapai target {max_candles} lilin tertutup.")
                                break

                        current_candle = norm

                        if on_tick:
                            await self._safe_callback(on_tick, norm)

            except asyncio.CancelledError:
                break
            except websockets.ConnectionClosed as e:
                logger.warning(f"Koneksi WebSocket IQ Option terputus: {e}. Mencoba menghubungkan kembali dalam 2 detik...")
                self.ws = None
                self.is_connected = False
                await asyncio.sleep(2)
                try:
                    await self.connect_ws()
                    await self.ws.send(json.dumps(sub_msg))
                    logger.info("✅ Berhasil menghubungkan kembali dan berlangganan ulang stream IQ Option.")
                except Exception as rec_err:
                    logger.error(f"Gagal menghubungkan kembali ke IQ Option: {rec_err}")
                    await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Error saat menerima stream IQ Option: {e}")
                await asyncio.sleep(1)

    async def _safe_callback(self, cb, data):
        if asyncio.iscoroutinefunction(cb):
            await cb(data)
        else:
            cb(data)

    def _normalize_single_candle(self, c):
        """Standarisasi format lilin IQ Option ke dictionary Python konsisten"""
        from_ts = int(c.get("from", c.get("time", 0)))
        open_p = float(c.get("open", 0.0))
        close_p = float(c.get("close", open_p))
        high_p = float(c.get("max", c.get("high", max(open_p, close_p))))
        low_p = float(c.get("min", c.get("low", min(open_p, close_p))))
        vol = float(c.get("volume", 0.0))

        return {
            "from": from_ts,
            "timestamp": datetime.fromtimestamp(from_ts, tz=timezone.utc),
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": vol,
        }

    def _normalize_candles(self, raw_list):
        candles = []
        for c in raw_list:
            if isinstance(c, dict) and "from" in c and "open" in c:
                candles.append(self._normalize_single_candle(c))
            elif isinstance(c, (list, tuple)) and len(c) >= 5:
                # Format list [time, open, close, high, low, volume]
                from_ts = int(c[0])
                candles.append({
                    "from": from_ts,
                    "timestamp": datetime.fromtimestamp(from_ts, tz=timezone.utc),
                    "open": float(c[1]),
                    "close": float(c[2]),
                    "high": float(c[3]),
                    "low": float(c[4]),
                    "volume": float(c[5]) if len(c) > 5 else 0.0,
                })
        # Urutkan berdasarkan waktu naik (kronologis)
        candles.sort(key=lambda x: x["from"])
        return candles

    def _generate_demo_candles(self, name, active_id, size_seconds, count, end_ts):
        """Membuat lilin demo sintetis realistis untuk simulasi pengujian tanpa kredensial"""
        # Tentukan basis harga awal
        if 'BTC' in name:
            base_price = 68500.0
            volat = 25.0
        elif 'ETH' in name:
            base_price = 2650.0
            volat = 3.0
        elif 'JPY' in name:
            base_price = 152.50
            volat = 0.05
        elif 'XAU' in name or 'GOLD' in name:
            base_price = 2650.0
            volat = 1.2
        else:
            base_price = 1.08500
            volat = 0.00015

        candles = []
        curr_price = base_price
        start_ts = end_ts - (count * size_seconds)

        for i in range(count):
            c_time = start_ts + (i * size_seconds)
            delta = (random.random() - 0.49) * volat * 2
            o = curr_price
            c = round(o + delta, 5 if base_price < 500 else 2)
            h = round(max(o, c) + abs(random.random() * volat * 0.8), 5 if base_price < 500 else 2)
            l = round(min(o, c) - abs(random.random() * volat * 0.8), 5 if base_price < 500 else 2)
            vol = round(random.uniform(50, 450), 1)

            candles.append({
                "from": c_time,
                "timestamp": datetime.fromtimestamp(c_time, tz=timezone.utc),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            })
            curr_price = c

        return candles

    async def _run_demo_stream(self, name, active_id, size_seconds, on_tick, on_candle_close, max_candles):
        """Simulasi streaming lilin real-time untuk pengujian pipeline"""
        base_price = 1.08500 if 'JPY' not in name else 152.50
        curr_price = base_price
        curr_candle_start = int(time.time() // size_seconds) * size_seconds
        candle_count = 0

        logger.info(f"🚀 Memulai simulasi live tick IQ Option untuk {name} (ID: {active_id})...")

        while True:
            now_ts = int(time.time())
            candle_start = int(now_ts // size_seconds) * size_seconds

            # Cek pergantian lilin
            if candle_start > curr_candle_start:
                candle_count += 1
                closed_candle = {
                    "from": curr_candle_start,
                    "timestamp": datetime.fromtimestamp(curr_candle_start, tz=timezone.utc),
                    "open": round(base_price, 5),
                    "high": round(base_price + 0.00020, 5),
                    "low": round(base_price - 0.00018, 5),
                    "close": round(curr_price, 5),
                    "volume": round(random.uniform(80, 200), 1),
                }
                if on_candle_close:
                    await self._safe_callback(on_candle_close, closed_candle)

                if max_candles > 0 and candle_count >= max_candles:
                    break

                curr_candle_start = candle_start
                base_price = curr_price

            # Tick update
            delta = (random.random() - 0.495) * 0.00008
            curr_price = round(curr_price + delta, 5)
            tick_candle = {
                "from": curr_candle_start,
                "timestamp": datetime.fromtimestamp(curr_candle_start, tz=timezone.utc),
                "open": round(base_price, 5),
                "high": round(max(base_price, curr_price) + 0.00005, 5),
                "low": round(min(base_price, curr_price) - 0.00005, 5),
                "close": curr_price,
                "volume": round(random.uniform(10, 50), 1),
            }
            if on_tick:
                await self._safe_callback(on_tick, tick_candle)

            await asyncio.sleep(1.0)

    async def close(self):
        """Menutup koneksi WebSocket"""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
        self.is_connected = False

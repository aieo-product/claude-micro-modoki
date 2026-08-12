"""Codex Micro との HID 通信層 (vendor JSON-RPC プロトコル)。

純正ファームは Report ID 6 / usage page 0xFF00 の双方向 vendor チャネルで
JSON-RPC を話す (ChatGPT.app の @worklouder/device-kit-oai を解析して判明)。

フレーム: [0x06, channel, chunkLen, <payload...>] = 64byte 固定
  channel: 1=debug / 2=RPC
  61byte を超えるメッセージは複数レポートに分割、受信側は改行(\\r\\n)まで結合

受信 (device→host):
  通知  {"m":"v.oai.hid","p":{"k":"ACT06","act":1}}   キーイベント
        {"m":"v.oai.rad","p":{"a":0.49,"d":0.5}}        ジョイスティック(angle,distance)
  応答  {"result":{...},"id":<n>,"method":"..."}        RPC 応答
  act: 1=押下 / 0=離す / 2=リピート(エンコーダー回転)

送信 (host→device、RPC):
  v.oai.thstatus  params=[{id,c,b,e,s,sk,sa}]              スレッド(エージェントキー)別ライティング
  v.oai.rgbcfg    params={ambient:{e,b,s,m,c},keys:{...}}   キー背面＋アンビエントリング
  color=packed RGB int / brightness,speed=0..1 / effect enum(下記) / magic=予備
  effect: 0=off 1=solid 2=snake 3=rainbow 4=breath 5=gradient 6=shallowBreath

macOS: 排他 open は ChatGPT アプリと競合するため非排他に設定 (下記 ctypes)。
open にはターミナル/プロセスへの入力監視権限が必要。
"""

import ctypes
import itertools
import json
import threading
import time

try:
    import hid
except ImportError:  # hidapi 未導入でも bridge 自体は起動できるようにする
    hid = None
else:
    # macOS: デフォルトの排他 open (seize) は ChatGPT アプリ等が掴んでいると失敗する。
    # cython-hidapi は Python API に出していないため C シンボルを直接叩いて非排他にする
    try:
        ctypes.CDLL(hid.__file__).hid_darwin_set_open_exclusive(0)
    except (OSError, AttributeError):
        pass  # macOS 以外 or シンボルなし

RETRY_INTERVAL_SEC = 3.0
READ_TIMEOUT_MS = 50
CHANNEL_RPC = 0x02
MAX_CHUNK = 61
# device.status ハートビート間隔。純正アプリは 60s。これが途絶えるとデバイスは
# エージェントモードを抜け、キーイベント(v.oai.hid)を vendor チャネルに送らなくなる。
# 実機検証: ハンドシェイク+ハートビートでキー入力が復活する（docs/vendor-protocol.md）
HEARTBEAT_SEC = 30.0

# effect enum
EFFECT = {"off": 0, "solid": 1, "snake": 2, "rainbow": 3,
          "breath": 4, "gradient": 5, "shallowBreath": 6}

# 承認状態 → スレッドライティング (color=packed RGB, effect, speed, brightness)
STATE_LIGHTING = {
    "idle":    {"c": 0x0A2A6E, "e": EFFECT["solid"],  "b": 0.15, "s": 0},    # 青微灯
    "pending": {"c": 0xFFB000, "e": EFFECT["breath"], "b": 1.0,  "s": 0.4},  # 黄点滅
    "accept":  {"c": 0x00FF00, "e": EFFECT["solid"],  "b": 1.0,  "s": 0},    # 緑
    "fallback": {"c": 0xB000FF, "e": EFFECT["solid"], "b": 1.0,  "s": 0},    # 紫(HOLD)
    "deny":    {"c": 0xFF0000, "e": EFFECT["solid"],  "b": 1.0,  "s": 0},    # 赤
    "off":     {"c": 0,        "e": EFFECT["off"],    "b": 0,    "s": 0},
}


class HidAdapter:
    """vendor JSON-RPC でキーイベント受信と LED 制御を行う。

    on_gesture(key_name, gesture): gesture = "tap"|"double"|"long"
    on_raw_key(key_name): 学習用 (押下の瞬間に発火)
    key_name は装置準拠の文字列 (ACT01..ACT12 / AG01..AG06 / ENC_CW / ENC_CC / ENC_CLK)
    """

    def __init__(self, vid: int, pid: int, timings: dict,
                 on_gesture=None, on_raw_key=None):
        self.vid, self.pid = vid, pid
        self.timings = timings
        self.on_gesture = on_gesture or (lambda k, g: None)
        self.on_raw_key = on_raw_key or (lambda k: None)
        self.status = {"found": False, "open": False, "error": None, "fw": None}
        self._stop = threading.Event()
        self._dev = None
        self._dev_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._rxbuf = bytearray()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._last_heartbeat = 0.0
        self._keys: dict[str, dict] = {}  # key_name -> ジェスチャー状態

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def update_timings(self, timings: dict):
        self.timings = timings

    # ---- LED 制御 ----

    def set_agent_led(self, index: int, state: str):
        """エージェントキー (スレッド) 1 本を状態色にする。index は 1..6、内部 thread id は 0-origin"""
        lit = STATE_LIGHTING.get(state, STATE_LIGHTING["idle"])
        self._rpc("v.oai.thstatus", [{"id": index - 1, "c": lit["c"], "b": lit["b"],
                                      "e": lit["e"], "s": lit["s"]}])

    def set_all_agent_leds(self, states: dict[int, str]):
        """複数エージェントキーを一括更新。states = {index: state}"""
        params = []
        for index, state in states.items():
            lit = STATE_LIGHTING.get(state, STATE_LIGHTING["idle"])
            params.append({"id": index - 1, "c": lit["c"], "b": lit["b"],
                           "e": lit["e"], "s": lit["s"]})
        if params:
            self._rpc("v.oai.thstatus", params)

    def set_ambient(self, state: str):
        lit = STATE_LIGHTING.get(state, STATE_LIGHTING["off"])
        side = {"e": lit["e"], "b": lit["b"], "s": lit["s"], "m": 0, "c": lit["c"]}
        self._rpc("v.oai.rgbcfg", {"ambient": side, "keys": STATE_LIGHTING["off"] | {"m": 0}})

    # 旧 IF 互換 (bridge 側が set_led(index, state) を呼ぶ)
    def set_led(self, key_index: int, state: str):
        self.set_agent_led(key_index, state)

    # ---- internal: 送受信 ----

    def _handshake(self):
        """接続直後にデバイスをエージェントモードへ。純正アプリの接続シーケンス再現。
        これを送らないとキーイベント(v.oai.hid)が vendor チャネルに流れない（実機検証済み）。"""
        self._rpc("device.status", None)
        self._last_heartbeat = time.monotonic()

    def _rpc(self, method: str, params):
        payload = {"id": next(self._ids), "m": method}
        if params is not None:
            payload["p"] = params
        msg = json.dumps(payload, separators=(",", ":")).encode() + b"\r\n"
        with self._dev_lock:
            dev = self._dev
            if dev is None:
                return
            try:
                for off in range(0, len(msg), MAX_CHUNK):
                    chunk = msg[off:off + MAX_CHUNK]
                    report = bytes([0x06, CHANNEL_RPC, len(chunk)]) + chunk
                    dev.write(list(report.ljust(64, b"\x00")))
            except (OSError, ValueError) as e:
                self.status["error"] = f"write error: {e}"

    def _run(self):
        while not self._stop.is_set():
            if hid is None:
                self.status["error"] = "hidapi 未導入"
                return
            dev = self._try_open()
            if dev is None:
                self._stop.wait(RETRY_INTERVAL_SEC)
                continue
            with self._dev_lock:
                self._dev = dev
            self.status.update(open=True, error=None)
            self._handshake()  # デバイスをエージェントモードに入れる（キーイベント有効化）
            try:
                self._read_loop(dev)
            except (OSError, ValueError) as e:
                self.status.update(open=False, error=f"read error: {e}")
            finally:
                with self._dev_lock:
                    self._dev = None
                try:
                    dev.close()
                except Exception:
                    pass
                self.status["open"] = False

    def _try_open(self):
        infos = hid.enumerate(self.vid, self.pid)
        self.status["found"] = bool(infos)
        if not infos:
            self.status["error"] = "デバイス未検出"
            return None
        dev = hid.device()
        try:
            dev.open(self.vid, self.pid)
            return dev
        except (OSError, ValueError):
            self.status["error"] = "open失敗 (入力監視権限が必要な可能性)"
            return None

    def _read_loop(self, dev):
        while not self._stop.is_set():
            data = dev.read(64, timeout_ms=READ_TIMEOUT_MS)
            now = time.monotonic()
            if data and data[0] == 0x06 and data[1] == CHANNEL_RPC:
                ln = data[2]
                self._rxbuf.extend(bytes(data[3:3 + ln]))
                self._drain_lines(now)
            if now - self._last_heartbeat >= HEARTBEAT_SEC:
                self._rpc("device.status", None)  # エージェントモード維持
                self._last_heartbeat = now
            self._tick(now)

    def _drain_lines(self, now: float):
        while b"\n" in self._rxbuf:
            line, _, rest = self._rxbuf.partition(b"\n")
            self._rxbuf = bytearray(rest)
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except ValueError:
                continue
            self._handle_message(obj, now)

    def _handle_message(self, obj: dict, now: float):
        method = obj.get("m") or obj.get("method")
        if method == "v.oai.hid":  # キーイベント通知
            p = obj.get("p", {})
            key, act = p.get("k"), p.get("act")
            if key is None:
                return
            if act == 1:
                self._on_press(key, now)
            elif act == 0:
                self._on_release(key, now)
            elif act == 2:  # エンコーダー回転など: 単発 tap 相当で通知
                self.on_gesture(key, "tap")
        elif method == "device.status":  # ハートビート応答: FW/バッテリー反映
            r = obj.get("result", {})
            if isinstance(r, dict):
                self.status["fw"] = r.get("version", self.status.get("fw"))
                self.status["battery"] = r.get("battery")
        # v.oai.rad (ジョイスティック) は現状未使用

    def _on_press(self, key: str, t: float):
        self.on_raw_key(key)
        st = self._keys.setdefault(key, {})
        st["pressed_at"] = t
        st["long_fired"] = False

    def _on_release(self, key: str, t: float):
        st = self._keys.get(key)
        if st is None or st.get("pressed_at") is None:
            return
        st["pressed_at"] = None
        if st.pop("long_fired", False):
            return
        double_win = self.timings["double_window_ms"] / 1000
        last_tap = st.get("last_tap")
        if last_tap is not None and (t - last_tap) <= double_win:
            st["last_tap"] = None
            st["pending_tap_at"] = None
            self.on_gesture(key, "double")
        else:
            st["last_tap"] = t
            st["pending_tap_at"] = t  # double 待ちで保留、_tick で確定

    def _tick(self, t: float):
        long_min = self.timings["long_min_ms"] / 1000
        double_win = self.timings["double_window_ms"] / 1000
        for k, st in self._keys.items():
            pa = st.get("pressed_at")
            if pa is not None and not st.get("long_fired") and (t - pa) >= long_min:
                st["long_fired"] = True
                self.on_gesture(k, "long")
            pt = st.get("pending_tap_at")
            if pt is not None and (t - pt) > double_win:
                st["pending_tap_at"] = None
                self.on_gesture(k, "tap")

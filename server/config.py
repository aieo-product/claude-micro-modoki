"""設定ファイルの読み書き。console UI (PUT /api/config) と bridge 本体が共有する。"""

import copy
import json
import os
import threading

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")

DEFAULT_CONFIG = {
    # LED 全体輝度 (%)。実機反映は vendor プロトコル解明後 (T0-4)
    "brightness": 100,
    # 無操作でライトオフにするまでの分数。0 = 無効
    "auto_dim_minutes": 3,
    # ジェスチャー → 承認結果のマッピング (accept=allow / fallback=ask / deny)
    "gestures": {"tap": "accept", "double": "fallback", "long": "deny"},
    "timings": {"tap_max_ms": 400, "double_window_ms": 350, "long_min_ms": 600},
    # エージェントキーの割当方式: recent = 最近のセッションに自動割当 (LRU)
    "agent_keys": {"mode": "recent"},
    # hook_client 側タイムアウト(240s)より先に応答するためのブリッジ側タイムアウト
    "approval_timeout_sec": 230,
    # 物理キー割当: key_id ("k<reportID>:<code>") -> {pos, role, index, label}
    #   role: agent(index必須) / accept / fallback / deny / none
    "keys": {},
    "device": {"vid": "0x303A", "pid": "0x8360"},
}

_lock = threading.Lock()


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    with _lock:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return _deep_merge(DEFAULT_CONFIG, json.load(f))
        except FileNotFoundError:
            return copy.deepcopy(DEFAULT_CONFIG)


def save(cfg: dict) -> dict:
    merged = _deep_merge(DEFAULT_CONFIG, cfg)
    with _lock:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged

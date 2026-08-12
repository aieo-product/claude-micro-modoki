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
    # claude/codex モード切替 (issue #7: A/Cハイブリッド)
    #   toggle_key: このキーの tap でモード手動トグル / long で auto に戻す
    #   auto: 前面アプリ監視で自動切替 (Codexアプリ前面時=codex / それ以外=claude)
    #   ambient_*: モード表示のアンビエントリング(枠)色 packed RGB。claude=オレンジ系/codex=青系
    "mode": {
        "current": "claude",       # 起動時のモード
        "toggle_key": "ACT12",     # マイク右隣・右下ボタン (実機確認済み)
        "auto": True,              # 前面アプリ自動切替を有効化
        "codex_app": "ChatGPT",    # 前面アプリ名がこれなら codex
        "ambient_claude": 0xD97757,  # Claude コーラル (オレンジ系)
        "ambient_codex": 0x0A84FF,   # 青系
        "ambient_brightness": 0.5,
    },
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

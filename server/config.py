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
    # tap/double/long の検出タイミング (承認はアクションキーで行うため gesture→承認マッピングは廃止)
    "timings": {"tap_max_ms": 400, "double_window_ms": 350, "long_min_ms": 600},
    # エージェントキーの割当方式: recent = 最近のセッションに自動割当 (LRU)
    "agent_keys": {"mode": "recent"},
    # hook_client 側タイムアウト(240s)より先に応答するためのブリッジ側タイムアウト
    "approval_timeout_sec": 230,
    # 物理キー割当: key_id ("k<reportID>:<code>") -> {pos, role, index, label}
    #   role: agent(index必須) / accept / fallback / deny / none
    "keys": {},
    "device": {"vid": "0x303A", "pid": "0x8360"},
    # モード (issue #7 → #11: 4モード claude-app/codex-app/cmux-claude/cmux-codex)
    #   toggle_key: tap で enabled モードを循環 / long で auto に戻す
    #   auto: 前面アプリ監視で自動切替
    #   enabled: 循環対象のモード。ambient は色=family(claude/codex)、エフェクト=context(app/cmux)
    "mode": {
        "current": "cmux-claude",  # 起動時のモード
        "toggle_key": "ACT12",     # マイク右隣・右下ボタン (実機確認済み)
        "auto": True,              # 前面アプリ自動切替
        "enabled": ["claude-app", "codex-app", "cmux-claude", "cmux-codex"],
        "codex_app": "ChatGPT",    # この前面アプリ名なら codex 系
        "cmux_app": "cmux",        # この前面アプリ名なら cmux 系
        "ambient_claude": 0xD97757,  # Claude コーラル (family=claude)
        "ambient_codex": 0x0A84FF,   # 青 (family=codex)
        "ambient_brightness": 0.5,
    },
    # cmux CLI パス (タブ制御・docs/cmux-integration.md)
    "cmux_cli": "/Applications/cmux.app/Contents/Resources/bin/cmux",
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

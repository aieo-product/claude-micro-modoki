"""設定ファイルの読み書き。console UI (PUT /api/config) と bridge 本体が共有する。"""

import copy
import json
import os
import sys
import threading


def _default_config_path() -> str:
    """config.json の場所。ソース実行時はリポジトリ直下 (gitignore 済み)。
    PyInstaller (.app/.exe) ではバンドル内が書き込み不可の展開先になるため、
    OS ごとのユーザー設定ディレクトリに保存する (#37)。"""
    if not getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(__file__), "..", "config.json")
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ClaudeMicro", "config.json")


CONFIG_PATH = _default_config_path()

DEFAULT_CONFIG = {
    # LED 全体輝度 (%)。実機反映は vendor プロトコル解明後 (T0-4)
    "brightness": 100,
    # 無操作でライトオフにするまでの分数。0 = 無効
    "auto_dim_minutes": 3,
    # tap/double/long の検出タイミング (承認はアクションキーで行うため gesture→承認マッピングは廃止)
    "timings": {"tap_max_ms": 400, "double_window_ms": 350, "long_min_ms": 600},
    # エージェントキーの割当方式: recent = 最近のセッションに自動割当 (LRU)
    "agent_keys": {"mode": "recent"},
    # アナログスティック(十字): 各方向にアクション id を割当 (#34)。デバイス実行は #35。
    "analog_stick": {
        "up": "plan-mode",
        "right": "forward",
        "down": "sidebar-toggle",
        "left": "back",
    },
    # ノブ(右上ダイヤル) (#34): mode=挙動プリセット。custom 時のみ rotate/click/long を使用。
    #   mode: input-nav(入力欄内移動) / inference(推論エフォート) / scroll(会話スクロール) / custom
    "knob": {
        "mode": "scroll",
        "rotate_cw": "scroll-down",
        "rotate_ccw": "scroll-up",
        "click": "interrupt",
        "long_press": "plan-mode",
    },
    # マイクキー(幅広) (#34): mode=push-to-talk/toggle/off。separate=下2スイッチを個別割当。
    "mic_key": {"mode": "push-to-talk", "separate_switches": False},
    # オプション (#34)
    "options": {"single_tap_focus": False},
    # codex-app 用ショートカットのユーザー上書き (#55)。公式アプリ側で割り当てた
    # キーをここに登録すると、コード変更なしに送出できる。
    #   action id -> {"text_key": "p", "modifiers": ["command", "option"]}
    "codex_app_shortcuts": {},
    # 端末(claude系/cmux-codex)向けキーストロークのユーザー上書き (#55)。
    # 明示指定があれば claude 固有ガードより優先する(ユーザーが意図した割当を尊重)。
    "terminal_shortcuts": {},
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
        # frozen 実行の初回保存ではユーザー設定ディレクトリがまだ無い (#37)
        parent = os.path.dirname(CONFIG_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged

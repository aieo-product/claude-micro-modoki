"""公式 Codex アプリのデバイス設定 (~/.codex/config.toml) を読み取り、本アプリ設定へ変換する (#53)。

公式アプリで Codex Micro を設定済みのユーザーが、本アプリ側で再設定せずに済むようにする。
**読み取り専用**: 公式 config は決して書き換えない。
"""

from __future__ import annotations

import os

try:  # tomllib は Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - 3.10 以下では取り込み機能を無効化
    tomllib = None

DEFAULT_CODEX_CONFIG = os.path.join(os.path.expanduser("~"), ".codex", "config.toml")

# 公式 encoderMode → 本アプリ knob.mode
ENCODER_MODE_MAP = {
    "reasoning": "inference",
    "inputNavigation": "input-nav",
    "input-navigation": "input-nav",
    "scroll": "scroll",
    "conversationScroll": "scroll",
    "custom": "custom",
}

# 公式 voiceButtonMode → 本アプリ mic_key.mode
VOICE_MODE_MAP = {
    "push-to-talk": "push-to-talk",
    "pushToTalk": "push-to-talk",
    "toggle": "toggle",
    "off": "off",
    "disabled": "off",
}

# 公式 analogStick commandId → 本アプリ action id (実機で観測した値のみ)
COMMAND_ID_MAP = {
    "composer.togglePlanMode": "plan-mode",
    "navigateForward": "forward",
    "navigateBack": "back",
    "toggleSidebar": "sidebar-toggle",
}

# 公式 keycapId → 本アプリ action id (意味が明確なもののみ。曖昧なものは意図的に未対応)
KEYCAP_MAP = {
    "APPR": "approve",
    "REJ": "reject",
    "FAST": "fast",
    "UNDO": "undo",
    "REDO": "redo",
    "CODEX": "codex-focus",
    "DIFF": "diff",
    "GIT": "git",
    "BRANCH": "branch",
    "MRG": "merge",
    "NEW": "new-session",
    "TERM": "focus-term",
    "PLAY": "play",
    "DRAFT": "draft",
    "NAV": "navigate",
    "MAGIC": "magic",
    "BUG": "debug",
    "DWN": "download",
    "TIME": "history",
    "SETUP": "setup",
}

STICK_DIRECTIONS = ("up", "right", "down", "left")


def load_official(path: str | None = None) -> dict | None:
    """公式 config.toml を読む。無い/読めない/tomllib 不在なら None。"""
    if tomllib is None:
        return None
    target = path or DEFAULT_CODEX_CONFIG
    try:
        with open(target, "rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return None


def to_bridge_config(official: dict) -> tuple[dict, list[str]]:
    """公式 config の dict から、本アプリ設定への差分 dict と未対応項目の注記を返す。

    返り値の dict は PUT /api/config と同じ形（部分更新）。公式に無い項目は含めない。
    """
    out: dict = {}
    notes: list[str] = []
    desktop = official.get("desktop") or {}
    layout = desktop.get("codex-micro-layout") or {}

    brightness = desktop.get("codex-micro-lighting-brightness")
    if isinstance(brightness, int) and not isinstance(brightness, bool):
        out["brightness"] = max(0, min(100, brightness))

    single_tap = desktop.get("codex-micro-single-tap-agent-keys")
    if isinstance(single_tap, bool):
        out["options"] = {"single_tap_focus": single_tap}

    knob: dict = {}
    enc = layout.get("encoderMode")
    if isinstance(enc, str):
        mapped = ENCODER_MODE_MAP.get(enc)
        if mapped:
            knob["mode"] = mapped
        else:
            notes.append(f"未知の encoderMode: {enc}")
    if knob:
        out["knob"] = knob

    mic: dict = {}
    voice = layout.get("voiceButtonMode")
    if isinstance(voice, str):
        mapped = VOICE_MODE_MAP.get(voice)
        if mapped:
            mic["mode"] = mapped
        else:
            notes.append(f"未知の voiceButtonMode: {voice}")
    sep = layout.get("separateMicrophoneKeys")
    if isinstance(sep, bool):
        mic["separate_switches"] = sep
    if mic:
        out["mic_key"] = mic

    stick_src = layout.get("analogStick") or {}
    stick: dict = {}
    for direction in STICK_DIRECTIONS:
        entry = stick_src.get(direction) or {}
        if entry.get("type") not in (None, "command"):
            notes.append(f"未対応の割当種別: {entry.get('type')} ({direction})")
            continue
        command_id = entry.get("commandId")
        if not isinstance(command_id, str):
            continue
        action = COMMAND_ID_MAP.get(command_id)
        if action:
            stick[direction] = action
        else:
            notes.append(f"未対応の commandId: {command_id} ({direction})")
    if stick:
        out["analog_stick"] = stick

    slots = layout.get("slots") or {}
    unmapped_slots = [
        f"{slot}={(spec or {}).get('keycapId')}"
        for slot, spec in slots.items()
        if isinstance(spec, dict) and spec.get("keycapId")
        and spec.get("keycapId") not in KEYCAP_MAP
    ]
    if unmapped_slots:
        notes.append("キーキャップ未対応: " + ", ".join(sorted(unmapped_slots)))

    return out, notes


def slot_actions(official: dict) -> dict[str, str]:
    """slots の keycapId を本アプリ action id に変換して返す (key_id -> action)。

    物理位置(pos)は公式 config に無いため、既存 binding がある key_id のみ更新する用途。
    """
    layout = (official.get("desktop") or {}).get("codex-micro-layout") or {}
    result: dict[str, str] = {}
    for slot, spec in (layout.get("slots") or {}).items():
        if not isinstance(spec, dict):
            continue
        action = KEYCAP_MAP.get(spec.get("keycapId"))
        if action:
            result[slot] = action
    return result


def slot_keycaps(official: dict) -> dict[str, str]:
    """slots の keycapId をそのまま返す (key_id -> keycapId)。console の刻印表示用 (#93)。

    値は未検証 (型が str であることのみ確認)。呼び出し側で actions.KEYCAP_IDS により
    ギャラリー内の刻印だけに絞ること。"""
    layout = (official.get("desktop") or {}).get("codex-micro-layout") or {}
    result: dict[str, str] = {}
    for slot, spec in (layout.get("slots") or {}).items():
        if isinstance(spec, dict) and isinstance(spec.get("keycapId"), str):
            result[slot] = spec["keycapId"]
    return result

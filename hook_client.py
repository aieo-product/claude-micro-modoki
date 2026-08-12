"""Claude Code hook → bridge クライアント (v2, issue #2/#4/#6)。

- PreToolUse: 承認要求として POST /decision（応答を permissionDecision に変換, フェイルクローズ）
- SessionStart / Stop / SessionEnd / Notification: POST /api/event（セッション登録・状態更新, フェイルオープン）

イベント系は bridge 停止中でも Claude をブロックしない（短タイムアウト・例外握り）。
cmux 内セッションは環境変数 CMUX_WORKSPACE_ID 等を捕捉して送る（エージェントキーの前面化に使用, #4）。
"""

import json
import os
import sys
import traceback

import requests

BRIDGE = "http://127.0.0.1:35703"
TOKEN = os.environ.get("APPROVAL_BRIDGE_TOKEN", "")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claudecode.log")
LOG_MAX = 512 * 1024  # 512KB 超で切り詰め


def log(msg: str):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX:
            with open(LOG, "r+", encoding="utf-8") as f:
                tail = f.read()[-LOG_MAX // 2:]
                f.seek(0); f.write(tail); f.truncate()
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg[:800] + "\n")
    except Exception:
        pass


def headers():
    return {"X-Bridge-Token": TOKEN} if TOKEN else {}


def cmux_env() -> dict:
    """cmux セッションの自己特定情報（#4: エージェントキー前面化に使う）。"""
    return {
        "cmux_workspace_id": os.environ.get("CMUX_WORKSPACE_ID"),
        "cmux_tab_id": os.environ.get("CMUX_TAB_ID"),
        "is_cmux": bool(os.environ.get("CMUX_BUNDLE_ID")),
    }


def handle_decision(data: dict) -> int:
    """PreToolUse: 承認。フェイルクローズ（bridge 不通/timeout/deny→deny 相当）。"""
    ti = json.dumps(data.get("tool_input") or {}, ensure_ascii=False)
    log(f"[PreToolUse] {data.get('tool_name')} {ti[:200]}")
    try:
        req = requests.post(f"{BRIDGE}/decision", json=data, headers=headers(), timeout=240)
    except requests.exceptions.ConnectionError:
        # bridge 停止中は手動承認に委ねる（ブロックしない = ask）
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask",
            "permissionDecisionReason": "bridge unreachable, manual approval"}}))
        return 0
    except Exception:
        log(traceback.format_exc())
        return 0
    if not req.ok:
        return 0
    result = req.json().get("result")
    decision, reason = {
        "accept": ("allow", "approved by bridge"),
        "fallback": ("ask", "held by bridge, manual approval"),
        "deny": ("deny", "denied by bridge"),
    }.get(result, ("deny", f"denied by bridge (result={result})"))  # timeout/不明→deny
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision,
        "permissionDecisionReason": reason}}))
    return 0


def handle_event(event: str, data: dict) -> int:
    """SessionStart/Stop/SessionEnd/Notification: 状態通知。フェイルオープン。"""
    payload = {
        "event": event,
        "session_id": data.get("session_id"),
        "cwd": data.get("cwd"),
        "source": data.get("source"),
        "message": data.get("message"),
        "env": cmux_env(),
    }
    log(f"[{event}] session={payload['session_id']} cmux={payload['env']['is_cmux']}")
    try:
        requests.post(f"{BRIDGE}/api/event", json=payload, headers=headers(), timeout=3)
    except Exception:
        pass  # bridge 停止中でも Claude を止めない
    return 0


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    event = data.get("hook_event_name") or "PreToolUse"
    if event == "PreToolUse":
        return handle_decision(data)
    return handle_event(event, data)


if __name__ == "__main__":
    sys.exit(main())

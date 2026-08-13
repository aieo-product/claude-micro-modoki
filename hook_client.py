"""Claude Code hook → bridge クライアント (v2, issue #2/#4/#6)。

- PreToolUse: 対象ツールを承認要求として POST /decision。**フェイルセーフ**: bridge の明示 deny/timeout は deny、
  それ以外の失敗(不通/HTTPタイムアウト/5xx/非JSON)は "ask"(手動承認)にフォールバックし、
  **決して auto-allow に素通りさせない**（承認ゲートが過負荷時に消えないようにする）。
- PreToolUse 以外のライフサイクルイベント: POST /api/event
  （フェイルオープン: Claude を止めない）。
  cmux 内セッションは CMUX_WORKSPACE_ID 等を捕捉して送る（エージェントキー前面化に使用, #4）。
"""

import json
import os
import sys
import traceback
import urllib.error
import urllib.request

try:
    import fcntl  # ログの排他ロック用 (macOS/Linux)
except ImportError:
    fcntl = None

# 依存なし・軽量のため stdlib urllib を使用（フックは毎イベント別プロセス起動のため import を最小化）
BRIDGE = "http://127.0.0.1:35703"
TOKEN = os.environ.get("APPROVAL_BRIDGE_TOKEN", "")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claudecode.log")
LOG_MAX = 512 * 1024  # 超過でローテーション(先頭を破棄)
DECISION_TIMEOUT = 240
DEFAULT_GATED_TOOLS = ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit")

# loopback 宛のトークン/cwd/tool_input を環境変数の外部 proxy へ流さない。
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(msg: str):
    """排他ロック下で追記。肥大時はローテーション。並行フックでも壊れない (#6)。"""
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            if fcntl:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                if f.tell() > LOG_MAX:
                    f.seek(0)
                    f.truncate()
                f.write(msg + "\n")
            finally:
                if fcntl:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


def post(path: str, payload: dict, timeout: float):
    """POST JSON。urllib.error.HTTPError(4xx/5xx) / URLError(不通/タイムアウト) を送出。"""
    body = json.dumps(payload).encode("utf-8")
    hdr = {"Content-Type": "application/json"}
    if TOKEN:
        hdr["X-Bridge-Token"] = TOKEN
    req = urllib.request.Request(BRIDGE + path, data=body, headers=hdr, method="POST")
    return opener.open(req, timeout=timeout)


def emit(decision: str, reason: str):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason}}))


def cmux_env() -> dict:
    return {
        "cmux_workspace_id": os.environ.get("CMUX_WORKSPACE_ID"),
        "cmux_tab_id": os.environ.get("CMUX_TAB_ID"),
        "is_cmux": bool(os.environ.get("CMUX_BUNDLE_ID")),
    }


def is_gated_tool(tool_name) -> bool:
    """環境変数の完全一致・末尾 * のプレフィックス一致で承認対象を判定。"""
    configured = os.environ.get("CLAUDEMICRO_GATED_TOOLS", "")
    gated_tools = tuple(entry.strip() for entry in configured.split(",") if entry.strip())
    if not gated_tools:
        gated_tools = DEFAULT_GATED_TOOLS
    if not isinstance(tool_name, str):
        return False
    return any(
        entry == "*"
        or (entry.endswith("*") and tool_name.startswith(entry[:-1]))
        or tool_name == entry
        for entry in gated_tools
    )


def handle_decision(data: dict) -> int:
    """PreToolUse: 承認。失敗時は ask(手動)にフォールバックし auto-allow させない (#3/#4)。"""
    ti = json.dumps(data.get("tool_input") or {}, ensure_ascii=False)
    log(f"[PreToolUse] {data.get('tool_name')} {ti[:200]}")
    try:
        raw = post("/decision", data, DECISION_TIMEOUT).read()
    except urllib.error.HTTPError as e:
        emit("ask", f"bridge HTTP {e.code} → 手動承認")  # #3: 5xx等でも手動(auto-allowさせない)
        return 0
    except Exception:
        log(traceback.format_exc()[:800])
        emit("ask", "bridge 不通/タイムアウト → 手動承認")  # #3: fail-safe
        return 0
    try:
        response = json.loads(raw)
        if not isinstance(response, dict):
            raise TypeError("bridge response is not an object")
        result = response.get("result")
    except (TypeError, ValueError):
        emit("ask", "bridge 非JSON応答 → 手動承認")  # #4: crashさせずfail-safe
        return 0
    if result == "accept":
        decision, reason = "allow", "approved by bridge"
    elif result == "fallback":
        decision, reason = "ask", "held by bridge, manual approval"
    elif result == "deny":
        decision, reason = "deny", "denied by bridge"
    else:
        decision, reason = "deny", f"denied by bridge (result={result})"  # timeout/不明→deny
    emit(decision, reason)
    return 0


def handle_event(event: str, data: dict) -> int:
    """PreToolUse 以外: 状態通知。フェイルオープン。
    ただし 401 等の失敗はログに残す（トークン不一致で全ライフサイクルが黙って落ちるのを可視化, #5）。"""
    payload = {
        "event": event,
        "family": "claude",
        "session_id": data.get("session_id"),
        "cwd": data.get("cwd"),
        "source": data.get("source"),
        "tool_name": data.get("tool_name"),
        "tool_input": data.get("tool_input"),
        "notification_type": data.get("notification_type"),
        "error_type": data.get("error_type"),
        "message": data.get("message") or data.get("error_message") or data.get("tool_error"),
        "turn_id": data.get("turn_id"),
        "env": cmux_env(),
    }
    log(f"[{event}] session={payload['session_id']} cmux={payload['env']['is_cmux']}")
    try:
        post("/api/event", payload, 3).read()
    except urllib.error.HTTPError as e:
        # 401 等はログに残す（トークン不一致で全ライフサイクルが黙って落ちるのを可視化, #5）
        log(f"[{event}] /api/event 失敗 HTTP {e.code}"
            + (" (APPROVAL_BRIDGE_TOKEN 不一致の可能性)" if e.code == 401 else ""))
    except Exception:
        pass  # bridge 停止中でも Claude を止めない
    return 0


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except (OSError, TypeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    event = data.get("hook_event_name") or "PreToolUse"
    if event == "PreToolUse":
        if not is_gated_tool(data.get("tool_name")):
            return 0
        return handle_decision(data)
    return handle_event(event, data)


if __name__ == "__main__":
    sys.exit(main())

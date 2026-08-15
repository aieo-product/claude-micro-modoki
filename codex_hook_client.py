"""Codex hook → bridge 観測クライアント。

Codex 自身の承認ポリシーに干渉せず、対応するライフサイクルイベントを
bridge の /api/event へ送る。bridge が停止している場合も Codex を止めない。
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
    # Windows など fcntl が使えない環境では、ログをロックなしで追記する。
    fcntl = None

# フックはイベントごとに起動するため、stdlib だけで軽量に保つ。
BRIDGE = "http://127.0.0.1:35703"
TOKEN = os.environ.get("APPROVAL_BRIDGE_TOKEN", "")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codexhook.log")
LOG_MAX = 512 * 1024
# Codex hook は observe-only。bridge 停止時も含め、フックの付加遅延を 0.5 秒未満に抑える。
EVENT_TIMEOUT = 0.4
SUPPORTED_EVENTS = frozenset({
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
    "SessionEnd",
    # エラー系は codex-cli 0.147.0 の実測でツール失敗でも未発火 (docs/event-sources.md §3.1)。
    # 将来 codex 側に追加されたとき素通しで error LED に届くよう前方互換で許可する (#75)
    "StopFailure",
    "PostToolUseFailure",
})

# loopback 宛のトークン/cwd/tool_input を環境変数の外部 proxy へ流さない。
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(msg: str):
    """ノンブロッキングロック下で追記。競合中は observe-only を優先してスキップ。"""
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            if fcntl:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return
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


def cmux_env() -> dict:
    """cmux 内の場所情報を bridge のセッション割当て用に渡す。"""
    return {
        "cmux_workspace_id": os.environ.get("CMUX_WORKSPACE_ID"),
        "cmux_tab_id": os.environ.get("CMUX_TAB_ID"),
        "is_cmux": bool(os.environ.get("CMUX_BUNDLE_ID")),
    }


def post_event(payload: dict):
    """bridge へイベントを POST する。"""
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Bridge-Token"] = TOKEN
    request = urllib.request.Request(
        BRIDGE + "/api/event", data=body, headers=headers, method="POST")
    return opener.open(request, timeout=EVENT_TIMEOUT)


def handle_event(event: str, data: dict) -> int:
    """観測イベントを送信する。応答内容は Codex へ返さない。"""
    payload = {
        "event": event,
        "family": "codex",
        "session_id": data.get("session_id"),
        "cwd": data.get("cwd"),
        "source": data.get("source"),
        "tool_name": data.get("tool_name"),
        "tool_input": data.get("tool_input"),
        "turn_id": data.get("turn_id"),
        "message": data.get("message") or data.get("last_assistant_message"),
        "env": cmux_env(),
    }
    if event in {"PreToolUse", "PostToolUse", "PermissionRequest"}:
        payload["tool_use_id"] = data.get("tool_use_id")
    log(f"[{event}] session={payload['session_id']} tool={payload['tool_name']}")
    try:
        with post_event(payload) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        suffix = " (APPROVAL_BRIDGE_TOKEN 不一致の可能性)" if exc.code == 401 else ""
        log(f"[{event}] /api/event 失敗 HTTP {exc.code}{suffix}")
    except Exception:
        # フックの不通は Codex の実行を妨げない。診断用にだけ残す。
        log(traceback.format_exc()[:800])
    return 0


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except (OSError, TypeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    event = data.get("hook_event_name")
    if not isinstance(event, str) or event not in SUPPORTED_EVENTS:
        return 0
    return handle_event(event, data)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""bridge にテスト用イベントを送り、エージェント状態の遷移を確認する。"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


DEFAULT_URL = "http://127.0.0.1:35703"
STEP_INTERVAL = 1.2
REQUEST_TIMEOUT = 5.0


# 正常終了と異常終了を含む、仕様の全状態を順に確認する。
EVENT_STEPS = (
    ("SessionStart", {"source": "fire_test_events"}),
    ("UserPromptSubmit", {}),
    (
        "PermissionRequest",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo claudemicro event test"},
        },
    ),
    (
        "PostToolUse",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo claudemicro event test"},
        },
    ),
    ("Stop", {}),
    (
        "StopFailure",
        {
            "error_type": "mock_error",
            "message": "テスト用の StopFailure",
        },
    ),
    ("SessionEnd", {}),
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="claude/codex のテストイベントを bridge に送信します。"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"bridge のベース URL（既定: {DEFAULT_URL}）",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("APPROVAL_BRIDGE_TOKEN", ""),
        help="共有トークン（既定: 環境変数 APPROVAL_BRIDGE_TOKEN）",
    )
    parser.add_argument(
        "--scenario",
        choices=("all", "claude", "codex"),
        default="all",
        help="発火対象（既定: all）",
    )
    return parser.parse_args(argv)


def event_url(base_url: str) -> str:
    """ベース URL と直接指定の /api/event の両方を受け付ける。"""
    url = base_url.rstrip("/")
    if url.endswith("/api/event"):
        return url
    return url + "/api/event"


def post_event(url: str, token: str, payload: dict) -> int:
    """イベントを POST し、成功時の HTTP ステータスを返す。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Bridge-Token"] = token
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        response.read()
        return response.status


def families_for(scenario: str):
    if scenario == "all":
        return ("claude", "codex")
    return (scenario,)


def payload_for(family: str, event: str, extra: dict) -> dict:
    payload = {
        "event": event,
        "family": family,
        "session_id": f"mock-{family}",
        "cwd": os.getcwd(),
        "env": {
            "cmux_workspace_id": None,
            "cmux_tab_id": None,
            "is_cmux": False,
        },
    }
    payload.update(extra)
    return payload


def format_error(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        try:
            detail = error.read(500).decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        suffix = f": {detail}" if detail else ""
        return f"HTTP {error.code}{suffix}"
    if isinstance(error, urllib.error.URLError):
        return f"接続エラー: {error.reason}"
    return str(error) or error.__class__.__name__


def run(args) -> int:
    target_url = event_url(args.url)
    families = families_for(args.scenario)
    successes = 0
    failures = []
    started_at = time.monotonic()

    print(f"送信先: {target_url}")
    print(f"シナリオ: {args.scenario} ({', '.join(families)})")

    # all では同じイベントを両 family に送り、2本のセッションを同時に観察できるようにする。
    for event, extra in EVENT_STEPS:
        for family in families:
            payload = payload_for(family, event, extra)
            label = f"{family:6} {event}"
            try:
                status = post_event(target_url, args.token, payload)
            except Exception as error:
                message = format_error(error)
                failures.append((family, event, message))
                print(f"NG  {label}: {message}", file=sys.stderr)
            else:
                successes += 1
                print(f"OK  {label}: HTTP {status}")
        # 最終状態の off もコンソールで確認できるよう、全ステップ後に待機する。
        time.sleep(STEP_INTERVAL)

    total = successes + len(failures)
    elapsed = time.monotonic() - started_at
    print(
        f"サマリ: 成功 {successes}/{total}, 失敗 {len(failures)}, "
        f"経過 {elapsed:.1f} 秒"
    )
    if failures:
        print("一部のイベント送信に失敗しました。", file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n中断しました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

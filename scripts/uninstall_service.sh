#!/usr/bin/env bash
# launchd から bridge のユーザーエージェントを削除する。

set -euo pipefail

LABEL="com.claudemicro.bridge"
USER_HOME="${HOME:?HOME が設定されていません}"
PLIST_PATH="$USER_HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN_TARGET="gui/$UID"
SERVICE_TARGET="$DOMAIN_TARGET/$LABEL"

usage() {
    echo "使い方: $0"
}

case "${1:-}" in
    "") ;;
    -h|--help)
        if [[ $# -ne 1 ]]; then
            echo "エラー: 引数が多すぎます。" >&2
            usage >&2
            exit 2
        fi
        usage
        exit 0
        ;;
    *)
        echo "エラー: 不明な引数です: $1" >&2
        usage >&2
        exit 2
        ;;
esac

if [[ $# -gt 0 ]]; then
    echo "エラー: 引数が多すぎます。" >&2
    usage >&2
    exit 2
fi
if ! command -v launchctl >/dev/null 2>&1; then
    echo "エラー: launchctl が見つかりません。macOS 上で実行してください。" >&2
    exit 1
fi
if launchctl print "$DOMAIN_TARGET" >/dev/null 2>&1; then
    MODERN=1
else
    MODERN=0
fi

# 選択した方式で登録解除し、不在を確認できた場合だけ plist を削除する。
if (( MODERN == 1 )); then
    # 未登録でも bootout は失敗するため、成否にかかわらず print で確認する。
    launchctl bootout "$SERVICE_TARGET" >/dev/null 2>&1 || true
    if launchctl print "$SERVICE_TARGET" >/dev/null 2>&1; then
        echo "エラー: launchd サービスを解除できませんでした: $SERVICE_TARGET" >&2
        echo "再試行できるよう plist を残します: $PLIST_PATH" >&2
        exit 1
    fi
else
    launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
    if ! SERVICE_LIST="$(launchctl list 2>/dev/null)"; then
        echo "エラー: launchd サービスの一覧を取得できませんでした。" >&2
        echo "再試行できるよう plist を残します: $PLIST_PATH" >&2
        exit 1
    fi
    if printf '%s\n' "$SERVICE_LIST" | grep -Fq -- "$LABEL"; then
        echo "エラー: launchd サービスを解除できませんでした: $LABEL" >&2
        echo "再試行できるよう plist を残します: $PLIST_PATH" >&2
        exit 1
    fi
fi
rm -f -- "$PLIST_PATH"

echo "launchd サービスを削除しました: $LABEL"
echo "plist: $PLIST_PATH"
echo "ログは残しています: $USER_HOME/Library/Logs/claudemicro/bridge.log"

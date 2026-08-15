#!/usr/bin/env bash
# bridge を launchd のユーザーエージェントとして登録する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
LABEL="com.claudemicro.bridge"
DEFAULT_PORT=35703
# インストール実行時の環境変数を plist の EnvironmentVariables へ取り込む (#73)。
# 未設定なら plist に書かず、bridge は従来どおり既定値で動く。
TOKEN="${APPROVAL_BRIDGE_TOKEN:-}"
PORT_ENV="${CLAUDEMICRO_PORT:-}"
if [[ -n "$PORT_ENV" ]]; then
    if [[ ! "$PORT_ENV" =~ ^[0-9]{1,5}$ ]] || (( 10#$PORT_ENV < 1 || 10#$PORT_ENV > 65535 )); then
        echo "エラー: CLAUDEMICRO_PORT が不正です: $PORT_ENV (1〜65535 の整数)" >&2
        exit 2
    fi
    PORT="$PORT_ENV"
else
    PORT="$DEFAULT_PORT"
fi
PYTHON="$REPO_DIR/.venv/bin/python"
USER_HOME="${HOME:?HOME が設定されていません}"
PLIST_DIR="$USER_HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$USER_HOME/Library/Logs/claudemicro"
LOG_PATH="$LOG_DIR/bridge.log"

xml_escape() {
    printf '%s' "$1" | sed \
        -e 's/&/\&amp;/g' \
        -e 's/</\&lt;/g' \
        -e 's/>/\&gt;/g'
}

render_plist() {
    local python_xml repo_xml log_xml
    python_xml="$(xml_escape "$PYTHON")"
    repo_xml="$(xml_escape "$REPO_DIR")"
    log_xml="$(xml_escape "$LOG_PATH")"

    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$python_xml</string>
        <string>-m</string>
        <string>server.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$repo_xml</string>
EOF

    if [[ -n "$TOKEN" || -n "$PORT_ENV" ]]; then
        echo "    <key>EnvironmentVariables</key>"
        echo "    <dict>"
        if [[ -n "$TOKEN" ]]; then
            printf '        <key>APPROVAL_BRIDGE_TOKEN</key>\n'
            printf '        <string>%s</string>\n' "$(xml_escape "$TOKEN")"
        fi
        if [[ -n "$PORT_ENV" ]]; then
            printf '        <key>CLAUDEMICRO_PORT</key>\n'
            printf '        <string>%s</string>\n' "$PORT_ENV"
        fi
        echo "    </dict>"
    fi

    cat <<EOF
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>$log_xml</string>
    <key>StandardErrorPath</key>
    <string>$log_xml</string>
</dict>
</plist>
EOF
}

usage() {
    echo "使い方: $0 [--dry-run]"
    echo "  --dry-run  plist の内容だけを表示し、ファイルや launchd を変更しません。"
}

case "${1:-}" in
    "") ;;
    --dry-run)
        if [[ $# -ne 1 ]]; then
            echo "エラー: 引数が多すぎます。" >&2
            usage >&2
            exit 2
        fi
        render_plist
        exit 0
        ;;
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
if [[ ! -x "$PYTHON" ]]; then
    echo "エラー: bridge 用 Python が実行できません: $PYTHON" >&2
    echo "先にリポジトリの .venv を準備してください。" >&2
    exit 1
fi
if ! command -v launchctl >/dev/null 2>&1; then
    echo "エラー: launchctl が見つかりません。macOS 上で実行してください。" >&2
    exit 1
fi

DOMAIN_TARGET="gui/$UID"
SERVICE_TARGET="$DOMAIN_TARGET/$LABEL"
if launchctl print "$DOMAIN_TARGET" >/dev/null 2>&1; then
    MODERN=1
else
    MODERN=0
fi
TEMP_PLIST=""
READY_PID=""

port_is_listening() {
    nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1
}

wait_for_port_to_be_free() {
    local deadline=$((SECONDS + 5))

    while port_is_listening; do
        if (( SECONDS >= deadline )); then
            return 1
        fi
        sleep 1
    done
}

modern_job_pid() {
    local service_info pid

    service_info="$(launchctl print "$SERVICE_TARGET" 2>/dev/null)" || return 1
    pid="$(printf '%s\n' "$service_info" | awk '
        /^[[:space:]]*pid = [1-9][0-9]*$/ { print $3; exit }
    ')"
    [[ -n "$pid" ]] || return 1
    printf '%s\n' "$pid"
}

legacy_job_pid() {
    local service_list pid

    service_list="$(launchctl list 2>/dev/null)" || return 1
    pid="$(printf '%s\n' "$service_list" | awk -v label="$LABEL" '
        $3 == label && $1 ~ /^[1-9][0-9]*$/ { print $1; exit }
    ')"
    [[ -n "$pid" ]] || return 1
    printf '%s\n' "$pid"
}

wait_for_readiness() {
    local deadline=$((SECONDS + 10))
    local pid

    while :; do
        pid=""
        if (( MODERN == 1 )); then
            if pid="$(modern_job_pid)" && port_is_listening; then
                READY_PID="$pid"
                return 0
            fi
        elif pid="$(legacy_job_pid)" && port_is_listening; then
            READY_PID="$pid"
            return 0
        fi

        if (( SECONDS >= deadline )); then
            return 1
        fi
        sleep 1
    done
}

rollback_started_job() {
    if (( MODERN == 1 )); then
        launchctl bootout "$SERVICE_TARGET" >/dev/null 2>&1
    else
        launchctl unload "$PLIST_PATH" >/dev/null 2>&1
    fi
}

cleanup() {
    if [[ -n "$TEMP_PLIST" && -e "$TEMP_PLIST" ]]; then
        rm -f -- "$TEMP_PLIST"
    fi
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$PLIST_DIR" "$LOG_DIR"
TEMP_PLIST="$(mktemp "$PLIST_DIR/.$LABEL.plist.XXXXXX")"
render_plist > "$TEMP_PLIST"
if [[ -n "$TOKEN" ]]; then
    chmod 0600 "$TEMP_PLIST"  # トークンを平文で含むため所有者のみ読み書き可 (#73)
else
    chmod 0644 "$TEMP_PLIST"
fi
mv -f -- "$TEMP_PLIST" "$PLIST_PATH"
TEMP_PLIST=""

# 再インストール時は、現在のジョブを外してから新しい plist を読み込む。
if (( MODERN == 1 )); then
    if ! launchctl bootout "$SERVICE_TARGET" >/dev/null 2>&1; then
        # 未登録でも bootout は失敗するため、残っている場合だけエラーにする。
        if launchctl print "$SERVICE_TARGET" >/dev/null 2>&1; then
            echo "エラー: 既存の launchd サービスを解除できませんでした: $SERVICE_TARGET" >&2
            exit 1
        fi
    elif launchctl print "$SERVICE_TARGET" >/dev/null 2>&1; then
        echo "エラー: 既存の launchd サービスを解除できませんでした: $SERVICE_TARGET" >&2
        exit 1
    fi
else
    launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
    if ! SERVICE_LIST="$(launchctl list 2>/dev/null)"; then
        echo "エラー: launchd サービスの一覧を取得できませんでした。" >&2
        exit 1
    fi
    if printf '%s\n' "$SERVICE_LIST" | grep -Fq -- "$LABEL"; then
        echo "エラー: 既存の launchd サービスを解除できませんでした: $LABEL" >&2
        exit 1
    fi
fi

if ! wait_for_port_to_be_free; then
    OCCUPYING_PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    echo "エラー: port $PORT が使用中です。手動起動中の bridge を停止してから再実行してください。" >&2
    if [[ -n "$OCCUPYING_PIDS" ]]; then
        echo "占有プロセスの PID: $(printf '%s\n' "$OCCUPYING_PIDS" | paste -sd ' ' -)" >&2
    else
        echo "占有プロセスの PID: 取得できませんでした" >&2
    fi
    exit 1
fi

if (( MODERN == 1 )); then
    if ! launchctl bootstrap "$DOMAIN_TARGET" "$PLIST_PATH"; then
        echo "エラー: launchctl bootstrap に失敗しました。" >&2
        exit 1
    fi
    if ! launchctl print "$SERVICE_TARGET" >/dev/null 2>&1; then
        echo "エラー: launchd サービスの登録を確認できませんでした: $SERVICE_TARGET" >&2
        exit 1
    fi
else
    if ! launchctl load -w "$PLIST_PATH"; then
        echo "エラー: launchctl load -w に失敗しました。" >&2
        exit 1
    fi
    if ! launchctl list | grep -Fq -- "$LABEL"; then
        echo "エラー: launchd サービスの登録を確認できませんでした: $LABEL" >&2
        exit 1
    fi
fi

if ! wait_for_readiness; then
    if ! rollback_started_job; then
        echo "警告: 起動に失敗した launchd サービスを解除できませんでした。" >&2
    fi
    echo "エラー: launchd サービスが10秒以内に起動しませんでした。" >&2
    echo "ログを確認してください: $LOG_PATH" >&2
    exit 1
fi

echo "launchd サービスをインストールしました: $PLIST_PATH"
if (( MODERN == 1 )) && SERVICE_INFO="$(launchctl print "$SERVICE_TARGET" 2>/dev/null)"; then
    echo "launchd 状態 ($SERVICE_TARGET):"
    printf '%s\n' "$SERVICE_INFO" | awk '
        /^[[:space:]]*(state|pid|last exit code) =/ { print "  " $0 }
    '
elif (( MODERN == 1 )); then
    echo "launchd 状態を取得できませんでした: $SERVICE_TARGET" >&2
else
    echo "launchd 状態 ($LABEL):"
    echo "  pid = $READY_PID"
fi
if [[ -n "$TOKEN" ]]; then
    echo "注意: APPROVAL_BRIDGE_TOKEN を plist に平文で保存しました (権限 0600): $PLIST_PATH"
fi
echo "設定コンソール: http://127.0.0.1:$PORT/"

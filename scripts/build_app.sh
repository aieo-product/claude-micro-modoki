#!/usr/bin/env bash
# Build the macOS tray application bundle with the repository-local virtualenv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PYINSTALLER="$REPO_DIR/.venv/bin/pyinstaller"
SPEC_FILE="$REPO_DIR/pyinstaller/claudemicro.spec"
APP_BUNDLE="$REPO_DIR/dist/ClaudeMicro.app"

usage() {
    echo "使い方: $0"
    echo "  .venv の PyInstaller を使い、dist/ClaudeMicro.app を生成します。"
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

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "エラー: ClaudeMicro.app のビルドは macOS 上で実行してください。" >&2
    exit 1
fi
if [[ ! -x "$PYINSTALLER" ]]; then
    echo "エラー: .venv に PyInstaller が見つかりません: $PYINSTALLER" >&2
    echo "先に .venv/bin/pip install -r requirements-app.txt を実行してください。" >&2
    exit 1
fi
if [[ ! -f "$SPEC_FILE" ]]; then
    echo "エラー: PyInstaller spec が見つかりません: $SPEC_FILE" >&2
    exit 1
fi

cd "$REPO_DIR"
# `console=False` and `name="ClaudeMicro"` in the spec are PyInstaller's
# spec-file equivalents of --windowed and --name ClaudeMicro.
PYINSTALLER_CONFIG_DIR="$REPO_DIR/build/.pyinstaller-cache" \
    "$PYINSTALLER" \
    --noconfirm \
    --clean \
    --distpath "$REPO_DIR/dist" \
    --workpath "$REPO_DIR/build" \
    "$SPEC_FILE"

if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "エラー: ビルドは完了しましたが $APP_BUNDLE が見つかりません。" >&2
    exit 1
fi

echo "ビルド完了: $APP_BUNDLE"

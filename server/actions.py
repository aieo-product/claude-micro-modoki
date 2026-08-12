"""アクションカタログとモード定義（issue #5 / #11）。

編集可能な設定データとして持つ。アクションは scope で3分類:
  common  … claude・codex どちらのモードでも機能
  claude  … claude 系モード専用
  codex   … codex 系モード専用

各アクションの実処理は server/main.py 側でディスパッチする（ここは定義のみ）。
"""

# ---- モード定義（issue #11: 4モード） ----
# family: 枠の色（claude=コーラル / codex=青） / context: app or cmux（枠のエフェクト）
MODES = [
    {"id": "claude-app",  "label": "Claude アプリ",   "family": "claude", "context": "app"},
    {"id": "codex-app",   "label": "Codex アプリ",    "family": "codex",  "context": "app"},
    {"id": "cmux-claude", "label": "cmux (claude)",  "family": "claude", "context": "cmux"},
    {"id": "cmux-codex",  "label": "cmux (codex)",   "family": "codex",  "context": "cmux"},
]
MODE_IDS = [m["id"] for m in MODES]


def mode_family(mode_id: str) -> str:
    for m in MODES:
        if m["id"] == mode_id:
            return m["family"]
    return "claude"


def mode_context(mode_id: str) -> str:
    for m in MODES:
        if m["id"] == mode_id:
            return m["context"]
    return "app"


def mode_for(family: str, context: str) -> str | None:
    """(family, context) から mode id を引く。ACT12 の tap=family切替 / double=context切替 用。"""
    for m in MODES:
        if m["family"] == family and m["context"] == context:
            return m["id"]
    return None


# ---- アクションカタログ（issue #5 第一案・編集可能） ----
# id / label / icon(絵文字デフォルト) / scope
ACTIONS = [
    # 共通
    {"id": "approve",       "label": "承認",              "icon": "✅", "scope": "common"},
    {"id": "reject",        "label": "拒否",              "icon": "⛔", "scope": "common"},
    {"id": "hold",          "label": "保留 (ask)",        "icon": "⏸️", "scope": "common"},
    {"id": "focus-term",    "label": "ターミナル前面化",  "icon": "🖥️", "scope": "common"},
    {"id": "new-session",   "label": "新規セッション",    "icon": "➕", "scope": "common"},
    {"id": "next-session",  "label": "次のセッション",    "icon": "⏭️", "scope": "common"},
    {"id": "prev-session",  "label": "前のセッション",    "icon": "⏮️", "scope": "common"},
    {"id": "scroll-up",     "label": "スクロール↑",       "icon": "🔼", "scope": "common"},
    {"id": "scroll-down",   "label": "スクロール↓",       "icon": "🔽", "scope": "common"},
    {"id": "interrupt",     "label": "割り込み (Esc)",    "icon": "⏹️", "scope": "common"},
    # claude 専用
    {"id": "plan-mode",     "label": "プランモード切替",  "icon": "📋", "scope": "claude"},
    {"id": "compact",       "label": "/compact",          "icon": "🗜️", "scope": "claude"},
    {"id": "accept-edits",  "label": "編集自動承認",      "icon": "✏️", "scope": "claude"},
    {"id": "resume",        "label": "セッション再開",    "icon": "↩️", "scope": "claude"},
    {"id": "fast-opus",     "label": "ファスト (Opus)",   "icon": "⚡", "scope": "claude"},
    # codex 専用
    {"id": "fork",          "label": "FORK",              "icon": "🍴", "scope": "codex"},
    {"id": "fast-codex",    "label": "FAST (高速)",       "icon": "🚀", "scope": "codex"},
    {"id": "side-chat",     "label": "サイドチャット",    "icon": "💬", "scope": "codex"},
    {"id": "archive",       "label": "アーカイブ",        "icon": "🗄️", "scope": "codex"},
    {"id": "pin",           "label": "ピン留め",          "icon": "📌", "scope": "codex"},
    {"id": "temp-chat",     "label": "一時チャット",      "icon": "🕶️", "scope": "codex"},
    {"id": "new-window",    "label": "新しいウィンドウ",  "icon": "🪟", "scope": "codex"},
    {"id": "diff",          "label": "DIFF",              "icon": "🔀", "scope": "codex"},
    {"id": "git",           "label": "GIT",               "icon": "🔧", "scope": "codex"},
    {"id": "pr",            "label": "PR",                "icon": "🔃", "scope": "codex"},
    {"id": "branch",        "label": "ブランチ作成",      "icon": "🌿", "scope": "codex"},
    {"id": "env-1",         "label": "環境アクション1",   "icon": "🎛️", "scope": "codex"},
    {"id": "env-2",         "label": "環境アクション2",   "icon": "🎛️", "scope": "codex"},
    {"id": "env-3",         "label": "環境アクション3",   "icon": "🎛️", "scope": "codex"},
]
ACTION_IDS = {a["id"] for a in ACTIONS}


def action_scope(action_id: str) -> str | None:
    for a in ACTIONS:
        if a["id"] == action_id:
            return a["scope"]
    return None


# ---- アイコンピッカー用の絵文字パレット（本家キーキャップ風） ----
ICON_CHOICES = [
    "✅", "⛔", "⏸️", "🖥️", "➕", "⏭️", "⏮️", "🔼", "🔽", "⏹️",
    "📋", "🗜️", "✏️", "↩️", "⚡", "🍴", "🚀", "💬", "🗄️", "📌",
    "🕶️", "🪟", "🔀", "🔧", "🔃", "🌿", "🎛️", "⭐", "🐛", "🔍",
    "▶️", "🎨", "🧪", "⏱️", "🔔", "📦", "🤖", "🎯", "🧠", "🔒",
]

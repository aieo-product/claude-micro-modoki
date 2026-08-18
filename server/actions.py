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
# id / label / icon(絵文字デフォルト) / scope / official
# official: 本家 Codex Micro の設定体系(キーキャップ既定・割当ドロップダウン・
# オプション)に対応が確認できるか (#59)。省略時は True(本家相当)。
# False の項目は本アプリ固有として UI で明示する(判断: 削除せず分類のみ)。
ACTIONS = [
    # 共通
    {"id": "approve",       "label": "承認",              "icon": "✅", "scope": "common"},
    {"id": "reject",        "label": "拒否",              "icon": "⛔", "scope": "common"},
    {"id": "hold",          "label": "保留 (ask)",        "icon": "⏸️", "scope": "common", "official": False},  # Claude 承認3択の ask
    {"id": "focus-term",    "label": "ターミナル前面化",  "icon": "🖥️", "scope": "common"},
    {"id": "new-session",   "label": "新規セッション",    "icon": "➕", "scope": "common"},
    {"id": "next-session",  "label": "次のセッション",    "icon": "⏭️", "scope": "common"},
    {"id": "prev-session",  "label": "前のセッション",    "icon": "⏮️", "scope": "common"},
    {"id": "scroll-up",     "label": "スクロール↑",       "icon": "🔼", "scope": "common"},
    {"id": "scroll-down",   "label": "スクロール↓",       "icon": "🔽", "scope": "common"},
    {"id": "interrupt",     "label": "割り込み (Esc)",    "icon": "⏹️", "scope": "common"},
    {"id": "undo",          "label": "元に戻す",          "icon": "↺", "scope": "common"},   # 本家 UNDO キーキャップ (#58)
    {"id": "redo",          "label": "やり直す",          "icon": "↻", "scope": "common"},   # 本家 REDO キーキャップ (#58)
    {"id": "fast",          "label": "FAST (高速モード)", "icon": "⚡", "scope": "common"},  # fast-opus/fast-codex を統合 (#59)
    # コントロール系（十字/ノブ/マイク割当用, #34。実処理は #35）
    {"id": "forward",        "label": "進む",              "icon": "▶️", "scope": "control"},
    {"id": "back",           "label": "前へ (戻る)",       "icon": "◀️", "scope": "control"},
    {"id": "sidebar-toggle", "label": "サイドバー切替",    "icon": "📚", "scope": "control"},
    {"id": "input-nav",      "label": "入力欄内の移動↑",   "icon": "⬆️", "scope": "control"},
    {"id": "input-nav-down", "label": "入力欄内の移動↓",   "icon": "⬇️", "scope": "control"},  # ノブ回転方向の再現 (#69)
    {"id": "inference-effort", "label": "推論エフォート↑", "icon": "🧠", "scope": "control"},
    {"id": "inference-effort-down", "label": "推論エフォート↓", "icon": "🧊", "scope": "control"},
    {"id": "scroll-convo",   "label": "会話スクロール",    "icon": "🖱️", "scope": "control"},
    {"id": "push-to-talk",   "label": "プッシュトゥトーク","icon": "🎙️", "scope": "control"},
    # スラッシュコマンド系 (#43)。official:False = 本家 Micro の設定体系に無い(本アプリ固有)
    {"id": "plan-mode",     "label": "プランモード切替",  "icon": "📋", "scope": "common"},  # 本家にも有(公式 commandId)
    {"id": "compact",       "label": "コンパクト",        "icon": "🗜️", "scope": "common", "official": False},
    {"id": "accept-edits",  "label": "承認モード切替",    "icon": "✏️", "scope": "common", "official": False},
    {"id": "resume",        "label": "セッション再開",    "icon": "↩️", "scope": "common", "official": False},
    # claude 専用 (現在は空。fast-opus は fast へ統合 #59)
    # codex 専用
    {"id": "fork",          "label": "FORK",              "icon": "🍴", "scope": "codex"},
    {"id": "side-chat",     "label": "サイドチャット",    "icon": "💬", "scope": "codex"},
    {"id": "archive",       "label": "アーカイブ",        "icon": "🗄️", "scope": "codex"},
    {"id": "pin",           "label": "ピン留め",          "icon": "📌", "scope": "codex"},
    {"id": "temp-chat",     "label": "一時チャット",      "icon": "🕶️", "scope": "codex"},
    {"id": "new-window",    "label": "新しいウィンドウ",  "icon": "🪟", "scope": "codex"},
    {"id": "diff",          "label": "DIFF",              "icon": "🔀", "scope": "codex"},
    {"id": "git",           "label": "GIT",               "icon": "🔧", "scope": "codex"},
    {"id": "pr",            "label": "PR",                "icon": "🔃", "scope": "codex"},
    {"id": "branch",        "label": "ブランチ作成",      "icon": "🌿", "scope": "codex"},
    {"id": "merge",         "label": "マージ",            "icon": "🔗", "scope": "codex"},
    {"id": "codex-focus",   "label": "Codex 前面化",      "icon": "🤖", "scope": "codex"},
    {"id": "debug",         "label": "デバッグ",          "icon": "🐛", "scope": "codex"},
    {"id": "download",      "label": "ダウンロード",      "icon": "📥", "scope": "codex"},
    {"id": "navigate",      "label": "ナビゲート",        "icon": "🧭", "scope": "codex"},
    {"id": "magic",         "label": "マジック",          "icon": "✨", "scope": "codex"},
    {"id": "play",          "label": "実行",              "icon": "▶️", "scope": "codex"},
    {"id": "draft",         "label": "ドラフト",          "icon": "📝", "scope": "codex"},
    {"id": "history",       "label": "履歴",              "icon": "🕐", "scope": "codex"},
    {"id": "thinking",      "label": "拡張思考",          "icon": "🧠", "scope": "codex"},
    {"id": "setup",         "label": "セットアップ",      "icon": "⚙️", "scope": "codex"},
    {"id": "env-1",         "label": "環境アクション1",   "icon": "🎛️", "scope": "codex"},
    {"id": "env-2",         "label": "環境アクション2",   "icon": "🎛️", "scope": "codex"},
    {"id": "env-3",         "label": "環境アクション3",   "icon": "🎛️", "scope": "codex"},
]
ACTION_IDS = {a["id"] for a in ACTIONS}

# 廃止 id → 後継 id (#59 FAST 統合)。config.load/save が既存設定を書き換える。
LEGACY_ACTION_IDS = {"fast-opus": "fast", "fast-codex": "fast"}


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


# ---- 本家キーキャップ刻印ギャラリー (#93) ----
# 本家「キーキャップを編集」モーダルのギャラリー (docs/codex-micro-official-ui.md §画面構成、
# 実機採取 33 種 + EMPT1–4)。id は刻印表示名。既定アクション (default) は採取ベースのみ
# (official_config.KEYCAP_MAP と同一の 18 種) で、未採取の刻印は既定なし = ユーザーが選ぶ。
# UNDO/REDO は公式ギャラリーで未確認のため載せない (#69 の差分レビュー参照)。
# glyph は console 表示用の絵文字 (本家は刻印画像。ここは代替表現)。
KEYCAPS = [
    {"id": "FAST",   "glyph": "⚡", "default": "fast"},
    {"id": "APPR",   "glyph": "✅", "default": "approve"},
    {"id": "REJ",    "glyph": "⛔", "default": "reject"},
    {"id": "FORK",   "glyph": "🍴", "default": None},
    {"id": "MIC1",   "glyph": "🎙️", "default": None},
    {"id": "CODEX",  "glyph": "🤖", "default": "codex-focus"},
    {"id": "BUG",    "glyph": "🐛", "default": "debug"},
    {"id": "OAI",    "glyph": "◎",  "default": None},
    {"id": "TERM",   "glyph": "🖥️", "default": "focus-term"},
    {"id": "DWN",    "glyph": "📥", "default": "download"},
    {"id": "DEL",    "glyph": "🗑️", "default": None},
    {"id": "NEW",    "glyph": "➕", "default": "new-session"},
    {"id": "NAV",    "glyph": "🧭", "default": "navigate"},
    {"id": "MAGIC",  "glyph": "✨", "default": "magic"},
    {"id": "DIFF",   "glyph": "🔀", "default": "diff"},
    {"id": "PLAY",   "glyph": "▶️", "default": "play"},
    {"id": "GIT",    "glyph": "🔧", "default": "git"},
    {"id": "DRAFT",  "glyph": "📝", "default": "draft"},
    {"id": "BRANCH", "glyph": "🌿", "default": "branch"},
    {"id": "MRG",    "glyph": "🔗", "default": "merge"},
    {"id": "PR",     "glyph": "🔃", "default": None},
    {"id": "PAINT",  "glyph": "🎨", "default": None},
    {"id": "LAB",    "glyph": "🧪", "default": None},
    {"id": "PARTY",  "glyph": "🎉", "default": None},
    {"id": "TIME",   "glyph": "🕐", "default": "history"},
    {"id": "MIND+",  "glyph": "🧠", "default": None},
    {"id": "MIND-",  "glyph": "🧊", "default": None},
    {"id": "EMPT1",  "glyph": "",   "default": None},
    {"id": "EMPT2",  "glyph": "",   "default": None},
    {"id": "EMPT3",  "glyph": "",   "default": None},
    {"id": "EMPT4",  "glyph": "",   "default": None},
    {"id": "SETUP",  "glyph": "⚙️", "default": "setup"},
    {"id": "FOLD",   "glyph": "📁", "default": None},
    {"id": "UPL",    "glyph": "📤", "default": None},
    {"id": "APPS",   "glyph": "🧩", "default": None},
    {"id": ":yolo:", "glyph": "🎲", "default": None},
    {"id": ":yeet:", "glyph": "🚀", "default": None},
]
KEYCAP_IDS = {k["id"] for k in KEYCAPS}


def keycap_default(keycap_id: str) -> str | None:
    """刻印の既定アクション id (採取ベース)。未知の刻印・既定なしは None。"""
    for k in KEYCAPS:
        if k["id"] == keycap_id:
            return k["default"]
    return None

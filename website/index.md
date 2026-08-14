---
layout: home

hero:
  name: claude-micro-modoki
  text: Claude Code を、手元の物理キーで承認する。
  tagline: Codex Micro（Work Louder 製マクロパッド）を Claude Code の承認コンソール & エージェント状態インジケーターに変えるブリッジ。Codex 純正「Agent Keys」の Claude Code 版（もどき）です。
  actions:
    - theme: brand
      text: 🚀 セットアップをはじめる
      link: /guide/setup
    - theme: alt
      text: 設計書を読む
      link: /design/architecture
    - theme: alt
      text: GitHub
      link: https://github.com/aieo-product/claude-micro-modoki

features:
  - icon: 🔑
    title: 物理キーで承認・拒否
    details: Claude Code のツール実行許可（PreToolUse hook）を、パッドのアクションキー1タップで allow / ask / deny。ターミナルに戻らず捌けます。
  - icon: 💡
    title: 6セッションを LED で可視化
    details: 6個のエージェントキーが各セッションの状態（待機・思考中・承認待ち・完了・エラー）を色で表示。押せばそのセッションを前面化。
  - icon: 🎛️
    title: claude / codex × app / cmux の4モード
    details: AI系統と文脈の2軸をキー1つで切替。codex-app モードでは実行だけ公式アプリへ委譲し、表示と設定は本アプリが統合します。
  - icon: 🪶
    title: 軽量・低負荷が最優先
    details: イベント駆動（hooks + FSEvents）でポーリングゼロ。常駐時 RSS 約50MB / CPU 約0.1%。複数 AI 運用でもマシンを圧迫しません。
  - icon: 🖥️
    title: 常駐もアプリ化も
    details: launchd 常駐スクリプト、メニューバー常駐のトレイアプリ（pystray + pywebview）、PyInstaller での .app ビルドに対応。
  - icon: 🤖
    title: Claude Desktop 対応（予定）
    details: ファームウェア書き換えにより、Claude Desktop 公式「ハードウェアバディ」(BLE) と直接つながる構想を進行中（issue #25 / #27 / #29）。
---

<div class="cm-home-section">

<h2>⌨️ デバイスと LED の対応</h2>
<p class="lead">Codex Micro の各キーに Claude Code のセッションとアクションが割り当てられます。</p>

<div class="cm-pad">
  <div class="row" style="grid-template-columns: 1.2fr 1fr 1fr 1fr;">
    <div class="cm-key round">🕹<small>ジョイスティック</small></div>
    <div class="cm-key">KEY</div>
    <div class="cm-key">KEY</div>
    <div class="cm-key round">◉<small>ノブ</small></div>
  </div>
  <div class="row" style="grid-template-columns: repeat(6, 1fr);">
    <div class="cm-key" style="--led:#5585E0;"><span class="dot"></span>AG00<small>待機</small></div>
    <div class="cm-key" style="--led:#5585E0;"><span class="dot"></span>AG01<small>思考中</small></div>
    <div class="cm-key" style="--led:#E8B24A;"><span class="dot"></span>AG02<small>承認待ち</small></div>
    <div class="cm-key" style="--led:#46C077;"><span class="dot"></span>AG03<small>完了</small></div>
    <div class="cm-key" style="--led:#E0584C;"><span class="dot"></span>AG04<small>エラー</small></div>
    <div class="cm-key"><span class="dot"></span>AG05<small>消灯</small></div>
  </div>
  <div class="row" style="grid-template-columns: repeat(4, 1fr);">
    <div class="cm-key" style="--led:#46C077;"><span class="dot"></span>承認<small>allow</small></div>
    <div class="cm-key" style="--led:#9C74E8;"><span class="dot"></span>保留<small>ask</small></div>
    <div class="cm-key" style="--led:#E0584C;"><span class="dot"></span>拒否<small>deny</small></div>
    <div class="cm-key hl">ACT12<small>モード切替</small></div>
  </div>
  <div class="row" style="grid-template-columns: 2.2fr 1fr;">
    <div class="cm-key">🎙 マイクキー</div>
    <div class="cm-key">CODEX</div>
  </div>
</div>

<h2>💡 LED 状態カラー</h2>
<p class="lead">エージェントキーの色 = そのセッションの今。ひと目で全セッションを把握できます。</p>

<div class="cm-strip">
  <span class="cm-led" style="--led:#ffffff;" title="idle"></span>
  <span class="cm-led" style="--led:#5585E0;" title="thinking"></span>
  <span class="cm-led breath" style="--led:#E8B24A;" title="input"></span>
  <span class="cm-led" style="--led:#46C077;" title="done"></span>
  <span class="cm-led" style="--led:#E0584C;" title="error"></span>
  <span class="cm-led" style="--led:#2a3040;" title="off"></span>
</div>

| <span class="cm-led" style="--led:#ffffff;"></span> idle | <span class="cm-led" style="--led:#5585E0;"></span> thinking | <span class="cm-led breath" style="--led:#E8B24A;"></span> input | <span class="cm-led" style="--led:#46C077;"></span> done | <span class="cm-led" style="--led:#E0584C;"></span> error | <span class="cm-led" style="--led:#2a3040;"></span> off |
|---|---|---|---|---|---|
| 待機中 | 推論・ツール実行中 | **承認待ち／入力待ち** | ターン完了 | API・ツールエラー | セッション終了 |

<h2>🔀 データの流れ</h2>
<p class="lead">hooks のイベントを HTTP で受け、raw HID でデバイスを駆動する — それだけのシンプルな一方向パイプラインです。</p>

<div class="cm-figure">
<svg viewBox="0 0 860 180" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="データフロー図">
  <defs>
    <marker id="cm-arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="currentColor" opacity=".6"/></marker>
    <marker id="cm-arr-accent" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#D97757"/></marker>
  </defs>
  <rect class="box" x="10" y="30" width="170" height="56" rx="10"/>
  <text x="95" y="54" text-anchor="middle">Claude Code / codex</text>
  <text x="95" y="72" text-anchor="middle" class="t-mono t-muted">hooks (31 events)</text>

  <rect class="box" x="230" y="30" width="160" height="56" rx="10"/>
  <text x="310" y="54" text-anchor="middle">hook_client.py</text>
  <text x="310" y="72" text-anchor="middle" class="t-mono t-muted">JSON payload</text>

  <rect class="box-accent" x="440" y="18" width="200" height="80" rx="10"/>
  <text x="540" y="46" text-anchor="middle">bridge（server/）</text>
  <text x="540" y="64" text-anchor="middle" class="t-mono t-muted">asyncio + aiohttp :35703</text>
  <text x="540" y="82" text-anchor="middle" class="t-mono t-muted">SessionRegistry / LED状態機</text>

  <rect class="box-dark" x="700" y="18" width="150" height="80" rx="14"/>
  <text x="775" y="50" text-anchor="middle" class="t-white">Codex Micro</text>
  <text x="775" y="70" text-anchor="middle" class="t-mono" fill="#8593A8">raw HID / LED</text>

  <path class="arrow" d="M182 58 H 226"/>
  <path class="arrow" d="M392 58 H 436"/>
  <path class="arrow-accent" d="M642 58 H 696"/>

  <text x="304" y="130" text-anchor="middle" class="t-mono t-muted t-small">HTTP POST /api/event ・ /decision</text>
  <text x="669" y="130" text-anchor="middle" class="t-mono t-muted t-small">Report ID 6 / JSON-RPC 64byte frame</text>
  <text x="540" y="160" text-anchor="middle" class="t-mono t-muted t-small">設定コンソール: http://127.0.0.1:35703/（モード切替・キー割当）</text>
</svg>
</div>

</div>

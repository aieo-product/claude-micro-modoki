import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'claude-micro-modoki',
  description:
    'Claude Code の承認操作とエージェント状態表示を Codex Micro の物理キーと LED で行うブリッジ',
  lang: 'ja-JP',
  base: '/claude-micro-modoki/',
  lastUpdated: true,
  head: [
    ['link', { rel: 'preconnect', href: 'https://fonts.googleapis.com' }],
    ['link', { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' }],
    [
      'link',
      {
        rel: 'stylesheet',
        href: 'https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500&family=Noto+Sans+JP:wght@400;500;700&display=swap'
      }
    ],
    [
      'link',
      {
        rel: 'icon',
        href: 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect x=%2210%22 y=%2210%22 width=%2280%22 height=%2280%22 rx=%2218%22 fill=%22%23D97757%22/><rect x=%2228%22 y=%2240%22 width=%2216%22 height=%2216%22 rx=%224%22 fill=%22%23fff%22/><rect x=%2256%22 y=%2240%22 width=%2216%22 height=%2216%22 rx=%224%22 fill=%22%23fff%22 opacity=%22.6%22/></svg>'
      }
    ]
  ],
  themeConfig: {
    siteTitle: 'claude-micro-modoki',
    nav: [
      { text: 'ガイド', link: '/guide/what-is', activeMatch: '/guide/' },
      { text: '設計書', link: '/design/architecture', activeMatch: '/design/' },
      { text: 'ロードマップ', link: '/design/roadmap' }
    ],
    sidebar: [
      {
        text: 'はじめる',
        items: [
          { text: 'claude-micro-modoki とは', link: '/guide/what-is' },
          { text: 'セットアップ（macOS）', link: '/guide/setup' },
          { text: '使い方（モードとキー操作）', link: '/guide/usage' },
          { text: 'Windows（実験的）', link: '/guide/windows' },
          { text: 'Claude Desktop 対応（予定）', link: '/guide/claude-desktop' }
        ]
      },
      {
        text: '設計書',
        items: [
          { text: '全体アーキテクチャ', link: '/design/architecture' },
          { text: 'イベント源とLED状態機', link: '/design/event-sources' },
          { text: 'vendor プロトコル (HID)', link: '/design/vendor-protocol' },
          { text: 'cmux 連携', link: '/design/cmux' },
          { text: 'ロードマップ', link: '/design/roadmap' }
        ]
      }
    ],
    socialLinks: [
      { icon: 'github', link: 'https://github.com/aieo-product/claude-micro-modoki' }
    ],
    outline: { level: [2, 3], label: 'このページ' },
    docFooter: { prev: '前へ', next: '次へ' },
    lastUpdatedText: '最終更新',
    darkModeSwitchLabel: '外観',
    sidebarMenuLabel: 'メニュー',
    returnToTopLabel: 'トップへ戻る',
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '検索', buttonAriaLabel: '検索' },
          modal: {
            noResultsText: '結果が見つかりません',
            resetButtonTitle: 'クリア',
            footer: { selectText: '選択', navigateText: '移動', closeText: '閉じる' }
          }
        }
      }
    },
    footer: {
      message: 'MIT License — upstream: © 2026 Mitsumine Suzu (verylowfreq) / fork: © 2026 aieo-product',
      copyright: 'Codex 純正「Agent Keys」の Claude Code 版（もどき）'
    }
  }
})

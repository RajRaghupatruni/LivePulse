/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_WEBSOCKET_BASE_URL?: string
  readonly VITE_CHATGPT_URL?: string
  readonly VITE_GITHUB_URL?: string
  readonly VITE_VSCODE_URL?: string
  readonly VITE_PORTFOLIO_URL?: string
  readonly VITE_STRATA_URL?: string
  readonly VITE_GMAIL_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

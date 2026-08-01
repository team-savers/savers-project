/// <reference types="vite/client" />

// Build-time global injected by `define` in vite.config.ts. Present so
// TypeScript knows the symbol exists; the value is a non-secret UTC timestamp
// plus short git sha used only as an on-screen "which build is live" marker.
declare const __BUILD_STAMP__: string

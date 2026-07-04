# FE-Widget — embeddable chat widget

A self-contained, style-isolated chat widget. A tiny loader paints a launcher bubble; the React
panel (reusing `chat-core` + `ChatPanel`, authored once) is dynamic-imported on first open and
mounted inside a **Shadow DOM** so tenant page CSS neither leaks in nor out.

## Build

```bash
npm run build:widget      # → frontend/dist-widget/widget.js (+ a lazy widget-panel-*.js chunk)
```

Serve `dist-widget/` from a static host / CDN. `widget.js` and its panel chunk must sit in the
same directory (the loader resolves the chunk relative to its own URL).

## Embed snippet

```html
<script
  type="module"
  async
  src="https://cdn.YOURHOST.com/widget.js"
  data-widget-key="wk_your_public_key"
  data-api-base="https://api.YOURHOST.com/api/v1"
></script>
```

- `data-widget-key` — the tenant's **public** widget key (from onboarding). Required.
- `data-api-base` — the API origin + `/api/v1`. Defaults to `/api/v1` (same-origin) if omitted.

## Content-Security-Policy the embedding site must allow ([IMP-FE-3])

The widget uses **no** inline `<style>`/`style=""` attributes: the `:host` reset is a constructable
stylesheet (`adoptedStyleSheets`) and component styles are applied via the CSSOM `style` property —
both are exempt from `style-src`. So a tenant only needs to allow the script + the API connection:

```
script-src  https://cdn.YOURHOST.com ;   # widget.js + its lazy panel chunk (ES module import)
connect-src https://api.YOURHOST.com ;    # POST /widget/session + the SSE turn stream
```

No `style-src 'unsafe-inline'`, `frame-src` (no iframe — Shadow DOM), `img-src`, or `font-src`
additions are required (system fonts + emoji only).

## Notes

- **Session continuity** — the server-minted `session_token` + conversation id are persisted in
  `localStorage` keyed by widget key, so a reload resumes the same conversation ([IMP-SEC-3]). The
  client never invents a session id.
- **Hosted page** — the same experience is available without embedding at
  `/chat/{widget_key}` (served by the SPA), useful for email/QR links.

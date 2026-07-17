/**
 * FE-Widget panel — the lazily-imported chunk. Mounts the SAME `Chat` component the SPA uses
 * (chat-core authored once, [IMP-FE-2]) into the loader's Shadow DOM. Styling is injected via
 * `adoptedStyleSheets` — a constructable stylesheet, NOT an inline <style> — so it survives a
 * strict Content-Security-Policy ([IMP-FE-3]); `:host{all:initial}` isolates the widget from the
 * host page's cascade in both directions.
 */

import { createRoot, type Root } from "react-dom/client";

import { Chat } from "../src/components/chat";

interface WidgetConfig {
  widgetKey: string;
  apiBase: string;
}

// The shadow root can't see the console's globals.css, so the shared ChatPanel's `var(--token)`
// reads are satisfied here: design tokens on :host (light + a prefers-color-scheme dark override
// so the widget follows the visitor's OS theme), plus the chat caret/spinner keyframes. Injected
// via a constructable stylesheet (NOT an inline <style>) to survive a strict CSP ([IMP-FE-3]).
const WIDGET_CSS = `
:host {
  all: initial;
  --brand-900: #1c1917;
  --brand-700: #5a3d24;
  --brand-500: #9c5326;
  --brand-200: #e8e7e2;
  --background: color-mix(in oklab, var(--brand-200) 22%, white);
  --foreground: var(--brand-900);
  --card: oklch(1 0 0);
  --secondary: var(--brand-200);
  --muted-foreground: var(--brand-500);
  --primary: var(--brand-900);
  --primary-foreground: var(--brand-200);
  --accent: color-mix(in oklab, var(--brand-500) 14%, white);
  --accent-foreground: var(--brand-900);
  --destructive: oklch(0.577 0.245 27.3);
  --border: color-mix(in oklab, var(--brand-500) 30%, white);
  --radius: 0.5rem;
  --font-mono: "Geist Mono Variable", ui-monospace, "SFMono-Regular", monospace;
}
@media (prefers-color-scheme: dark) {
  :host {
    --background: color-mix(in oklab, var(--brand-900) 92%, black 8%);
    --foreground: var(--brand-200);
    --card: color-mix(in oklab, var(--brand-900) 78%, var(--brand-700) 22%);
    --secondary: color-mix(in oklab, var(--brand-900) 80%, var(--brand-700) 20%);
    --muted-foreground: color-mix(in oklab, var(--brand-200) 55%, var(--brand-500) 20%);
    --primary: color-mix(in oklab, var(--brand-200) 92%, var(--brand-500) 8%);
    --primary-foreground: var(--brand-900);
    --accent: color-mix(in oklab, var(--brand-700) 45%, var(--brand-900) 55%);
    --accent-foreground: var(--brand-200);
    --destructive: oklch(0.704 0.19 22.2);
    --border: oklch(1 0 0 / 0.1);
  }
}
* { box-sizing: border-box; }
.cs-widget-root { height: 100%; background: var(--background); }
@keyframes cswblink { 50% { opacity: 0; } }
@keyframes cswspin { to { transform: rotate(360deg); } }
@keyframes cswfadein { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes cswbounce { 0%,80%,100% { transform: scale(0.6); opacity: 0.4; } 40% { transform: scale(1); opacity: 1; } }
/* Markdown for AI answers — mirror of the .chat-md rules in src/styles/globals.css. */
.chat-md { font-size: 15px; line-height: 1.6; overflow-wrap: break-word; }
.chat-md > :first-child { margin-top: 0; }
.chat-md > :last-child { margin-bottom: 0; }
.chat-md p { margin: 0 0 0.6em; }
.chat-md ul, .chat-md ol { margin: 0.4em 0; padding-inline-start: 1.35em; }
.chat-md ul { list-style: disc; }
.chat-md ol { list-style: decimal; }
.chat-md li { margin: 0.2em 0; }
.chat-md a { color: var(--primary); text-decoration: underline; text-underline-offset: 2px; }
.chat-md strong { font-weight: 600; }
.chat-md code { font-family: var(--font-mono, ui-monospace, monospace); font-size: 0.88em; background: var(--secondary); padding: 0.1em 0.35em; border-radius: 4px; }
.chat-md pre { background: var(--secondary); padding: 10px 12px; border-radius: 8px; overflow-x: auto; margin: 0.5em 0; }
.chat-md pre code { background: none; padding: 0; }
.chat-md h1, .chat-md h2, .chat-md h3 { font-weight: 600; line-height: 1.3; margin: 0.7em 0 0.3em; }
.chat-md h1 { font-size: 1.15em; }
.chat-md h2, .chat-md h3 { font-size: 1.05em; }
.chat-md blockquote { border-inline-start: 3px solid var(--border); padding-inline-start: 12px; color: var(--muted-foreground); margin: 0.5em 0; }
.chat-md table { display: block; width: max-content; max-width: 100%; overflow-x: auto; border-collapse: collapse; font-size: 0.92em; margin: 0.5em 0; }
.chat-md th, .chat-md td { border: 1px solid var(--border); padding: 4px 8px; text-align: start; }
.chat-md th { background: var(--secondary); font-weight: 600; }
/* Chat interactive states — MIRROR of the .csw-root block in src/styles/globals.css. Keep in sync. */
.csw-root { --csw-focus: color-mix(in srgb, var(--primary, #1C1917) 55%, transparent); }
.csw-root .csw-chip, .csw-root .csw-cite, .csw-root .csw-iconbtn, .csw-root .csw-send, .csw-root .csw-ghost, .csw-root .csw-jump {
  transition: transform 120ms cubic-bezier(0.22, 1, 0.36, 1), box-shadow 140ms ease, background-color 160ms ease, color 160ms ease, border-color 160ms ease, opacity 150ms ease;
}
.csw-root .csw-chip:hover { transform: translateY(-1px); border-color: var(--primary, #1C1917); }
.csw-root .csw-ghost:hover { transform: translateY(-1px); background: var(--secondary, #f1f5f9); }
.csw-root .csw-iconbtn:hover { background: var(--secondary, #f1f5f9); }
.csw-root .csw-cite { box-shadow: 0 1px 2px color-mix(in oklab, var(--foreground, #0f172a) 6%, transparent); }
.csw-root .csw-cite:hover { transform: translateY(-1px); box-shadow: 0 4px 12px color-mix(in oklab, var(--foreground, #0f172a) 12%, transparent); }
.csw-root .csw-chip:active, .csw-root .csw-ghost:active { transform: scale(0.97); }
.csw-root .csw-send:active { transform: scale(0.92); }
.csw-root .csw-jump:hover { background: var(--secondary, #f1f5f9); box-shadow: 0 6px 18px color-mix(in oklab, var(--foreground, #0f172a) 16%, transparent); }
.csw-root .csw-composer:focus-within { border-color: var(--primary, #1C1917); box-shadow: 0 0 0 3px var(--csw-focus); }
.csw-root :focus-visible { outline: 2px solid var(--csw-focus); outline-offset: 2px; }
.csw-root :focus:not(:focus-visible) { outline: none; }
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
`;

function adopt(root: ShadowRoot): void {
  try {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(WIDGET_CSS);
    root.adoptedStyleSheets = [...root.adoptedStyleSheets, sheet];
  } catch {
    // Very old engines without constructable stylesheets: the inline component styles still
    // render correctly; only the :host tokens/reset are skipped (chat falls back to its hex).
  }
}

export function mount(root: ShadowRoot, config: WidgetConfig): { unmount: () => void } {
  adopt(root);
  const container = document.createElement("div");
  container.className = "cs-widget-root";
  root.appendChild(container);
  const reactRoot: Root = createRoot(container);
  reactRoot.render(<Chat widgetKey={config.widgetKey} apiBase={config.apiBase} />);
  return { unmount: () => reactRoot.unmount() };
}

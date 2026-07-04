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

const RESET = `
:host { all: initial; }
* { box-sizing: border-box; }
.cs-widget-root { height: 100%; font-family: system-ui, -apple-system, sans-serif; }
`;

function adopt(root: ShadowRoot): void {
  try {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(RESET);
    root.adoptedStyleSheets = [...root.adoptedStyleSheets, sheet];
  } catch {
    // Very old engines without constructable stylesheets: the inline component styles still
    // render correctly; only the :host reset is skipped.
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

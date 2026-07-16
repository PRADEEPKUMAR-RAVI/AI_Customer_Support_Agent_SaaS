/**
 * FE-Widget loader — the tiny, framework-free entry a tenant embeds ([IMP-FE-7]).
 *
 *   <script type="module" async src=".../widget.js"
 *           data-widget-key="wk_xxx" data-api-base="https://api.example.com/api/v1"></script>
 *
 * It paints the launcher bubble immediately and only DYNAMIC-IMPORTS the (heavier) React panel
 * chunk on first open — so the code a page loads up-front stays minimal. The panel mounts inside
 * a Shadow DOM ([IMP-FE-3]) so tenant page CSS can neither leak in nor be leaked out. The session
 * is server-minted + persisted by chat-core ([IMP-SEC-3]); the loader never invents an id.
 */

interface WidgetConfig {
  widgetKey: string;
  apiBase: string;
}

const Z = "2147483000"; // above almost everything, below the max (leave room for tenant modals)
const BRAND = "#1B3C53"; // darkest brand step (matches the design system's primary)

const ICON_CHAT =
  '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
const ICON_CLOSE =
  '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>';

function readConfig(): WidgetConfig {
  const el = document.querySelector<HTMLScriptElement>("script[data-widget-key]");
  return {
    widgetKey: el?.dataset.widgetKey ?? "",
    apiBase: el?.dataset.apiBase ?? "/api/v1",
  };
}

function createHost(): HTMLElement {
  const host = document.createElement("div");
  Object.assign(host.style, {
    position: "fixed", right: "20px", bottom: "88px", width: "380px", height: "560px",
    maxWidth: "calc(100vw - 40px)", maxHeight: "calc(100vh - 120px)", zIndex: Z,
    borderRadius: "16px", overflow: "hidden", boxShadow: "0 12px 40px rgba(2,6,23,0.28)",
    border: "1px solid rgba(2,6,23,0.08)", background: "transparent", display: "none",
  });
  host.attachShadow({ mode: "open" });
  document.body.appendChild(host);
  return host;
}

function boot(): void {
  const cfg = readConfig();
  if (!cfg.widgetKey) return; // nothing to do without a key

  const bubble = document.createElement("button");
  bubble.innerHTML = ICON_CHAT;
  bubble.setAttribute("aria-label", "Open chat");
  Object.assign(bubble.style, {
    position: "fixed", right: "20px", bottom: "20px", width: "56px", height: "56px",
    display: "grid", placeItems: "center", borderRadius: "50%", border: "none",
    background: BRAND, color: "#fff", cursor: "pointer", zIndex: Z,
    boxShadow: "0 6px 20px rgba(79,70,229,0.45)", transition: "transform .15s ease",
  });
  bubble.addEventListener("mouseenter", () => (bubble.style.transform = "scale(1.06)"));
  bubble.addEventListener("mouseleave", () => (bubble.style.transform = "scale(1)"));

  let host: HTMLElement | null = null;
  let open = false;

  bubble.addEventListener("click", async () => {
    open = !open;
    bubble.innerHTML = open ? ICON_CLOSE : ICON_CHAT;
    bubble.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    if (open && !host) {
      host = createHost();
      const { mount } = await import("./panel"); // lazy — the panel chunk loads only now
      mount(host.shadowRoot as ShadowRoot, cfg);
    }
    if (host) host.style.display = open ? "block" : "none";
  });

  document.body.appendChild(bubble);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}

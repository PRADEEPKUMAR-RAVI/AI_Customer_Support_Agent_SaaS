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
    borderRadius: "12px", overflow: "hidden", boxShadow: "0 12px 32px rgba(0,0,0,0.25)",
    background: "#fff", display: "none",
  });
  host.attachShadow({ mode: "open" });
  document.body.appendChild(host);
  return host;
}

function boot(): void {
  const cfg = readConfig();
  if (!cfg.widgetKey) return; // nothing to do without a key

  const bubble = document.createElement("button");
  bubble.textContent = "💬";
  bubble.setAttribute("aria-label", "Open chat");
  Object.assign(bubble.style, {
    position: "fixed", right: "20px", bottom: "20px", width: "56px", height: "56px",
    borderRadius: "50%", border: "none", background: "#2563eb", color: "#fff", fontSize: "24px",
    cursor: "pointer", zIndex: Z, boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
  });

  let host: HTMLElement | null = null;
  let open = false;

  bubble.addEventListener("click", async () => {
    open = !open;
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

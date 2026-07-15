/**
 * Chrome i18n + direction. The AI answer is generated server-side in the customer's language;
 * these are the UI CHROME strings (composer, buttons, status filler). Locale + dir switch only
 * when the established `detected_language` changes ([C7]) — the controller drives that.
 *
 * Status labels localize the typed `status` SSE stages ([IMP-ENG-7]). POC ships en + es; the
 * map falls back to en for any other language so nothing renders blank.
 */

import type { StatusStage } from "../types/sse";

const RTL_LANGS = new Set(["ar", "he", "fa", "ur", "yi"]);

export type Dir = "rtl" | "ltr";

export function dirFor(lang: string): Dir {
  return RTL_LANGS.has((lang || "en").split("-")[0].toLowerCase()) ? "rtl" : "ltr";
}

export interface ChromeStrings {
  assistantName: string;
  assistantSubtitle: string;
  suggestions: string[];
  placeholder: string;
  send: string;
  talkToHuman: string;
  connecting: string;
  thumbUp: string;
  thumbDown: string;
  consentTitle: string;
  consentBody: string;
  consentAccept: string;
  retry: string;
  errorGeneric: string;
  status: Record<StatusStage, string>;
  // Added for the redesigned panel — all chrome-only (no logic/contract change).
  aiAgent: string; // subtle per-message "this reply is from the AI" caption (mixed transcripts)
  agentLabel: string; // a human support agent's label
  handoffSubtitle: string; // header subtitle once a human has taken over
  sources: string; // heading above citation cards
  copy: string;
  copied: string;
  jumpToLatest: string; // scroll-to-bottom affordance
  connectingHuman: string; // centered system note when a turn escalates
}

const EN: ChromeStrings = {
  assistantName: "Assistant",
  assistantSubtitle: "AI support · replies in seconds",
  suggestions: ["What's your return policy?", "Where is my order?", "How do I contact a human?"],
  placeholder: "Type a message…",
  send: "Send",
  talkToHuman: "Talk to a human",
  connecting: "Connecting…",
  thumbUp: "Helpful",
  thumbDown: "Not helpful",
  consentTitle: "Before we chat",
  consentBody: "Messages may be reviewed to improve support. Do not share sensitive personal data.",
  consentAccept: "Start chat",
  retry: "Retry",
  errorGeneric: "Something went wrong. Please try again.",
  status: {
    retrieving: "Searching the knowledge base…",
    looking_up: "Looking up your details…",
    generating: "Writing a reply…",
    waiting: "One moment…",
  },
  aiAgent: "AI Agent",
  agentLabel: "Support agent",
  handoffSubtitle: "A team member is helping you",
  sources: "Sources",
  copy: "Copy",
  copied: "Copied",
  jumpToLatest: "Jump to latest",
  connectingHuman: "Connecting you to a person…",
};

const ES: ChromeStrings = {
  assistantName: "Asistente",
  assistantSubtitle: "Soporte con IA · responde en segundos",
  suggestions: ["¿Cuál es su política de devoluciones?", "¿Dónde está mi pedido?", "¿Cómo hablo con una persona?"],
  placeholder: "Escribe un mensaje…",
  send: "Enviar",
  talkToHuman: "Hablar con una persona",
  connecting: "Conectando…",
  thumbUp: "Útil",
  thumbDown: "No útil",
  consentTitle: "Antes de chatear",
  consentBody: "Los mensajes pueden revisarse para mejorar el soporte. No compartas datos personales sensibles.",
  consentAccept: "Iniciar chat",
  retry: "Reintentar",
  errorGeneric: "Algo salió mal. Inténtalo de nuevo.",
  status: {
    retrieving: "Buscando en la base de conocimiento…",
    looking_up: "Consultando tus datos…",
    generating: "Escribiendo una respuesta…",
    waiting: "Un momento…",
  },
  aiAgent: "Agente IA",
  agentLabel: "Agente de soporte",
  handoffSubtitle: "Un miembro del equipo te está ayudando",
  sources: "Fuentes",
  copy: "Copiar",
  copied: "Copiado",
  jumpToLatest: "Ir al último",
  connectingHuman: "Conectándote con una persona…",
};

const TABLE: Record<string, ChromeStrings> = { en: EN, es: ES };

export function strings(lang: string): ChromeStrings {
  return TABLE[(lang || "en").split("-")[0].toLowerCase()] ?? EN;
}

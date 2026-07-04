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
}

const EN: ChromeStrings = {
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
};

const ES: ChromeStrings = {
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
};

const TABLE: Record<string, ChromeStrings> = { en: EN, es: ES };

export function strings(lang: string): ChromeStrings {
  return TABLE[(lang || "en").split("-")[0].toLowerCase()] ?? EN;
}

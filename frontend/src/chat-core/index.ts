/** chat-core public surface — framework-agnostic. React/Preact bindings live outside this dir. */

export { ChatController, type ChatControllerOptions } from "./controller";
export { applyEvent } from "./reducer";
export {
  createSession,
  resumeOrCreateSession,
  clearSession,
  type WidgetSession,
  type WidgetConfig,
} from "./session";
export { dirFor, strings, type Dir, type ChromeStrings } from "./i18n";
export {
  emptyAssistant,
  userMessage,
  type ChatState,
  type ChatMessage,
  type ChatRole,
  type ConnState,
} from "./types";

/** Mirrors the backend's frozen industry -> record_type registry
 * (`app/domain/records/schemas.py`) for display only — which template-download buttons to
 * render. Not a security boundary: the backend re-validates `record_type` against the
 * tenant's actual industry on every request. Same pattern as `lib/rbac.ts` mirroring the
 * backend's permission catalog for UI gating. */

export const RECORD_TYPES_BY_INDUSTRY: Record<string, string[]> = {
  retail: ["order", "warranty"],
  logistics: ["shipment"],
  telecom: ["subscription", "billing"],
  healthcare: ["appointment"],
  travel: ["booking"],
};

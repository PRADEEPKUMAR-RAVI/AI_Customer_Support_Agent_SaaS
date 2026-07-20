/** Derived onboarding-completion check — backs the forced-onboarding router guard. Mirrors the
 * same required steps `OnboardingPage.tsx`'s own `done` map checks (industry, knowledge, records,
 * config); allowed domains and staff are optional. See `app/api/v1/onboarding.py` for how
 * `completed` is computed server-side. */

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/api/generated/schema";

type OnboardingStatus = components["schemas"]["OnboardingStatusResponse"];

export function useOnboardingStatus() {
  return useQuery({
    queryKey: ["onboarding", "status"],
    queryFn: async () =>
      unwrap<OnboardingStatus>(await api.GET("/api/v1/onboarding/status")),
  });
}

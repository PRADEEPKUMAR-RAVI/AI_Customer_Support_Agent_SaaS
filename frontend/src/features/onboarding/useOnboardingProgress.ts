import { useDatasets, useDomains, useEmbed, useSettings, useSources, useStaff, useTenant } from "./queries";
import { useOnboardingStore } from "./store";
import { STEPS, type StepKey } from "./steps";

/** The one place "is step X done" is computed — used by both `OnboardingPage.tsx` (to render
 * checkmarks/gate Next) and `app-sidebar.tsx` (to render the same checkmarks/lock state in the
 * step list). Pulling this into a hook keeps the two views from drifting the way two independent
 * copies of this formula eventually would. */
export function useOnboardingProgress() {
  const confirmedSteps = useOnboardingStore((s) => s.confirmedSteps);

  const tenantQ = useTenant();
  const settingsQ = useSettings();
  const sourcesQ = useSources();
  const datasetsQ = useDatasets();
  const domainsQ = useDomains();
  const staffQ = useStaff();
  const embedQ = useEmbed();

  const tenant = tenantQ.data;

  const done: Record<StepKey, boolean> = {
    industry: !!tenant?.industry,
    // Not data-derived like the others: downloading a template produces no server-side record
    // (the upload happens later, in "records") — gating this on dataset presence made the step
    // impossible to pass on its own, since reaching the upload step required passing this one
    // first. Confirmed the same way "config"/"embed" are: an explicit action (clicking Download).
    templates: confirmedSteps.has("templates"),
    knowledge: (sourcesQ.data?.length ?? 0) > 0,
    records: (datasetsQ.data?.length ?? 0) > 0,
    config: confirmedSteps.has("config"),
    domains: (domainsQ.data?.length ?? 0) > 0,
    staff: (staffQ.data?.length ?? 0) > 1,
    embed: confirmedSteps.has("embed"),
  };
  const completed = STEPS.filter((s) => done[s.key]).length;

  const settled =
    !tenantQ.isLoading &&
    !settingsQ.isLoading &&
    !sourcesQ.isLoading &&
    !datasetsQ.isLoading &&
    !domainsQ.isLoading &&
    !staffQ.isLoading &&
    !embedQ.isLoading;

  return { tenant, tenantQ, done, completed, settled };
}

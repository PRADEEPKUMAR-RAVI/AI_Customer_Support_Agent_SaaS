import { useQuery } from "@tanstack/react-query";

import type { components } from "@/api/generated/schema";
import { api, unwrap } from "@/lib/api";

export type Tenant = components["schemas"]["TenantResponse"];
export type AgentSettings = components["schemas"]["AgentSettingsResponse"];
export type SourceOut = components["schemas"]["SourceOut"];
export type DatasetOut = components["schemas"]["DatasetOut"];
export type AllowedDomain = components["schemas"]["AllowedDomainResponse"];
export type Staff = components["schemas"]["StaffResponse"];
export type EmbedSnippet = components["schemas"]["EmbedSnippetResponse"];

/** Shared query hooks — keys aligned to sibling pages (Knowledge/Records/Staff/Channels) so
 * caches stay in sync, and to `app-sidebar.tsx` (via `useOnboardingProgress`), which needs the
 * same "is setup done yet" data the wizard itself computes. */

export function useTenant() {
  return useQuery({
    queryKey: ["tenant"],
    queryFn: async () => unwrap<Tenant>(await api.GET("/api/v1/admin/tenant")),
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: async () => unwrap<AgentSettings>(await api.GET("/api/v1/admin/settings")),
  });
}

export function useSources() {
  return useQuery({
    queryKey: ["kb", "sources"],
    queryFn: async () => {
      const page = unwrap(
        await api.GET("/api/v1/knowledge/sources", {
          params: { query: { limit: 50, offset: 0 } },
        })
      );
      return page.items;
    },
  });
}

export function useDatasets() {
  return useQuery({
    queryKey: ["records", "datasets"],
    queryFn: async () => unwrap<DatasetOut[]>(await api.GET("/api/v1/records/datasets")),
  });
}

export function useDomains() {
  return useQuery({
    queryKey: ["admin", "allowed-domains"],
    queryFn: async () => unwrap<AllowedDomain[]>(await api.GET("/api/v1/admin/allowed-domains")),
  });
}

export function useStaff() {
  return useQuery({
    queryKey: ["admin", "staff"],
    queryFn: async () => unwrap<Staff[]>(await api.GET("/api/v1/admin/staff")),
  });
}

export function useEmbed() {
  return useQuery({
    queryKey: ["embed-snippet"],
    queryFn: async () => unwrap<EmbedSnippet>(await api.GET("/api/v1/admin/embed-snippet")),
  });
}

/** FE-Analytics API wrappers over the typed client (date-filterable). */

import type { components } from "../../api/generated/schema";
import { api } from "../../lib/api";

export type AnalyticsOverview = components["schemas"]["AnalyticsOverview"];
export type LatencyStats = components["schemas"]["LatencyStats"];
export type CostStats = components["schemas"]["CostStats"];
export type TagStats = components["schemas"]["TagStats"];

type Range = { from?: string; to?: string };

const q = ({ from, to }: Range) => ({
  params: { query: { from_date: from || undefined, to_date: to || undefined } },
});

export async function getOverview(range: Range): Promise<AnalyticsOverview> {
  const { data, error } = await api.GET("/api/v1/analytics/overview", q(range));
  if (error) throw new Error("Failed to load overview");
  return data!;
}

export async function getLatency(range: Range): Promise<LatencyStats> {
  const { data, error } = await api.GET("/api/v1/analytics/latency", q(range));
  if (error) throw new Error("Failed to load latency");
  return data!;
}

export async function getCost(range: Range): Promise<CostStats> {
  const { data, error } = await api.GET("/api/v1/analytics/cost", q(range));
  if (error) throw new Error("Failed to load cost");
  return data!;
}

export async function getTags(range: Range): Promise<TagStats> {
  const { data, error } = await api.GET("/api/v1/analytics/tags", q(range));
  if (error) throw new Error("Failed to load tags");
  return data!;
}

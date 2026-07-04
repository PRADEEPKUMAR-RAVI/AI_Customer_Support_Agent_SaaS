/** FE-Knowledge API wrappers over the typed `openapi-fetch` client. */

import type { components } from "../../api/generated/schema";
import { api } from "../../lib/api";

export type SourceOut = components["schemas"]["SourceOut"];

export async function listSources(): Promise<SourceOut[]> {
  const { data, error } = await api.GET("/api/v1/knowledge/sources", {
    params: { query: { limit: 100, offset: 0 } },
  });
  if (error) throw new Error("Failed to list knowledge sources");
  return data?.items ?? [];
}

export async function createPasteSource(name: string, content: string): Promise<SourceOut> {
  const { data, error } = await api.POST("/api/v1/knowledge/sources/paste", {
    body: { name, content },
  });
  if (error) throw new Error("Failed to add pasted source");
  return data!;
}

export async function uploadFileSource(file: File, name?: string): Promise<SourceOut> {
  const { data, error } = await api.POST("/api/v1/knowledge/sources/file", {
    // Body typed to the multipart schema; bodySerializer emits the actual FormData.
    body: { file: file as unknown as string, name: name ?? null },
    bodySerializer() {
      const form = new FormData();
      form.append("file", file);
      if (name) form.append("name", name);
      return form;
    },
  });
  if (error) throw new Error("Failed to upload file source");
  return data!;
}

export async function createUrlSource(name: string, url: string): Promise<SourceOut> {
  const { data, error } = await api.POST("/api/v1/knowledge/sources/url", { body: { name, url } });
  if (error) throw new Error("Failed to add URL source");
  return data!;
}

export async function deleteSource(id: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/knowledge/sources/{source_id}", {
    params: { path: { source_id: id } },
  });
  if (error) throw new Error("Failed to delete source");
}

export async function reingestSource(id: string): Promise<SourceOut> {
  const { data, error } = await api.POST("/api/v1/knowledge/sources/{source_id}/reingest", {
    params: { path: { source_id: id } },
  });
  if (error) throw new Error("Failed to reingest source");
  return data!;
}

/** Knowledge source list with live ingestion-status polling (stops once all settle). */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Spinner } from "../../components";
import { deleteSource, listSources, reingestSource, type SourceOut } from "./api";

const STATUS_COLOR: Record<string, string> = {
  queued: "#a16207",
  ingesting: "#a16207",
  ready: "#15803d",
  failed: "#b91c1c",
};

const isActive = (s: SourceOut) => s.status === "queued" || s.status === "ingesting";

function RowActions({ source }: { source: SourceOut }) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["kb", "sources"] });
  const del = useMutation({ mutationFn: () => deleteSource(source.id), onSuccess: invalidate });
  const re = useMutation({ mutationFn: () => reingestSource(source.id), onSuccess: invalidate });
  const busy = source.status === "ingesting";
  return (
    <span style={{ display: "inline-flex", gap: 6 }}>
      <Button variant="ghost" disabled={busy || re.isPending} onClick={() => re.mutate()}>
        Reingest
      </Button>
      <Button variant="ghost" disabled={busy || del.isPending} onClick={() => del.mutate()}>
        Delete
      </Button>
    </span>
  );
}

export function SourceList() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["kb", "sources"],
    queryFn: listSources,
    // Poll only while something is still ingesting; stop when all are ready|failed.
    refetchInterval: (query) => {
      const items = query.state.data as SourceOut[] | undefined;
      return items?.some(isActive) ? 1500 : false;
    },
  });

  if (isLoading) return <Spinner />;
  if (isError) return <p role="alert">Failed to load knowledge sources.</p>;

  const items = data ?? [];
  return (
    <Card>
      <h3>Knowledge sources</h3>
      {items.length === 0 ? (
        <p>No sources yet — paste text or upload a .txt / .md file to get started.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "#6b7280" }}>
              <th>Name</th>
              <th>Kind</th>
              <th>Status</th>
              <th style={{ textAlign: "right" }}>Chunks</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id} style={{ borderTop: "1px solid #eee" }}>
                <td>{s.name}</td>
                <td>{s.kind}</td>
                <td style={{ color: STATUS_COLOR[s.status] ?? "#374151" }}>
                  {s.status}
                  {s.status === "failed" && s.error ? ` — ${s.error}` : ""}
                </td>
                <td style={{ textAlign: "right" }}>{s.chunk_count}</td>
                <td style={{ textAlign: "right" }}>
                  <RowActions source={s} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

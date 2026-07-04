/** FE-Records: per-record-type dataset upload with server validation report, dataset list +
 * delete, and a compact DB/API connector create + test. Mirrors the FE-Knowledge pattern. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "../../app/providers";
import { Button, Card, Spinner } from "../../components";
import { hasPermission } from "../../lib/rbac";
import {
  createConnector,
  deleteDataset,
  getRecordsSchema,
  listDatasets,
  testConnector,
  uploadDataset,
  type DatasetUploadReport,
  type RecordSchemaOut,
} from "./api";

function ValidationReport({ report }: { report: DatasetUploadReport }) {
  if (report.ok) {
    return <p style={{ color: "#15803d" }}>✓ Uploaded {report.inserted ?? 0} rows.</p>;
  }
  const missing = report.missing_headers ?? [];
  const dups = report.duplicate_keys ?? [];
  const rowErrors = report.row_errors ?? [];
  return (
    <div style={{ color: "#b91c1c", fontSize: 13 }}>
      <p>Upload rejected — nothing was saved.</p>
      {missing.length > 0 && <p>Missing headers: {missing.join(", ")}</p>}
      {dups.length > 0 && <p>Duplicate keys: {dups.join(", ")}</p>}
      {rowErrors.length > 0 && (
        <ul>
          {rowErrors.slice(0, 10).map((e) => (
            <li key={e.row}>row {e.row}: {e.error}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RecordTypeCard({ schema, rowCount }: { schema: RecordSchemaOut; rowCount: number | null }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<DatasetUploadReport | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["records", "datasets"] });
  const upload = useMutation({
    mutationFn: () => uploadDataset(schema.record_type, file as File),
    onSuccess: (r) => {
      setReport(r);
      if (r.ok) setFile(null);
      invalidate();
    },
  });
  const remove = useMutation({ mutationFn: () => deleteDataset(schema.record_type), onSuccess: invalidate });

  return (
    <Card>
      <h3>{schema.record_type}</h3>
      <p style={{ fontSize: 13, color: "#6b7280" }}>
        key: <b>{schema.key}</b>
        {(schema.alias_keys ?? []).length > 0 && <> (alias: {(schema.alias_keys ?? []).join(", ")})</>} ·
        verify: {(schema.verify_fields ?? []).join(" or ")} · fields:{" "}
        {(schema.returned_fields ?? []).join(", ")}
      </p>
      <p style={{ fontSize: 13 }}>{rowCount === null ? "No dataset uploaded" : `${rowCount} rows uploaded`}</p>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          type="file"
          accept=".csv,.json,text/csv,application/json"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Button disabled={!file || upload.isPending} onClick={() => upload.mutate()}>
          {upload.isPending ? "Uploading…" : "Upload CSV / JSON"}
        </Button>
        {rowCount !== null && (
          <Button variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
            Delete dataset
          </Button>
        )}
      </div>
      {report && <ValidationReport report={report} />}
    </Card>
  );
}

function ConnectorForm({ schemas }: { schemas: RecordSchemaOut[] }) {
  const [recordType, setRecordType] = useState(schemas[0]?.record_type ?? "");
  const [sourceType, setSourceType] = useState<"db" | "api">("db");
  const [credentials, setCredentials] = useState("");
  const [configText, setConfigText] = useState('{"query_template": "SELECT ... WHERE key = :key"}');
  const [fieldMapText, setFieldMapText] = useState('{"source_col": "schema_field"}');
  const [testKey, setTestKey] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      const connector = await createConnector({
        record_type: recordType,
        source_type: sourceType,
        credentials,
        config: JSON.parse(configText),
        field_map: JSON.parse(fieldMapText),
      });
      if (testKey.trim()) {
        const report = await testConnector(connector.id, testKey.trim());
        return report.ok ? "Saved + test OK" : `Saved, but test failed: ${report.error}`;
      }
      return "Connector saved.";
    },
    onSuccess: (m) => setMsg(m),
    onError: (e) => setMsg(`Error: ${(e as Error).message}`),
  });

  return (
    <Card>
      <h3>Connect a DB / API source</h3>
      <div style={{ display: "grid", gap: 8, maxWidth: 560 }}>
        <label>
          record type:{" "}
          <select value={recordType} onChange={(e) => setRecordType(e.target.value)}>
            {schemas.map((s) => (
              <option key={s.record_type}>{s.record_type}</option>
            ))}
          </select>
        </label>
        <label>
          source:{" "}
          <select value={sourceType} onChange={(e) => setSourceType(e.target.value as "db" | "api")}>
            <option value="db">db</option>
            <option value="api">api</option>
          </select>
        </label>
        <input
          placeholder={sourceType === "db" ? "DSN (encrypted at rest)" : "API auth secret"}
          value={credentials}
          onChange={(e) => setCredentials(e.target.value)}
        />
        <textarea rows={2} value={configText} onChange={(e) => setConfigText(e.target.value)} />
        <textarea rows={2} value={fieldMapText} onChange={(e) => setFieldMapText(e.target.value)} />
        <input placeholder="test key (optional)" value={testKey} onChange={(e) => setTestKey(e.target.value)} />
        <div>
          <Button disabled={!recordType || !credentials || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save + test connector"}
          </Button>
        </div>
        {msg && <p style={{ fontSize: 13 }}>{msg}</p>}
      </div>
    </Card>
  );
}

export function RecordsPage() {
  const { role } = useAuth();
  const schemaQ = useQuery({ queryKey: ["records", "schema"], queryFn: getRecordsSchema });
  const datasetsQ = useQuery({ queryKey: ["records", "datasets"], queryFn: listDatasets });

  if (role && !hasPermission(role, "records:manage")) {
    return <Card><p>You don't have permission to manage records.</p></Card>;
  }
  if (schemaQ.isLoading || datasetsQ.isLoading) return <Spinner />;
  if (schemaQ.isError) return <p role="alert">Failed to load the record schema.</p>;

  const schemas = schemaQ.data ?? [];
  const rowCounts = new Map((datasetsQ.data ?? []).map((d) => [d.record_type, d.row_count]));

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 820 }}>
      <h2>Customer records</h2>
      {schemas.map((s) => (
        <RecordTypeCard key={s.record_type} schema={s} rowCount={rowCounts.get(s.record_type) ?? null} />
      ))}
      {schemas.length > 0 && <ConnectorForm schemas={schemas} />}
    </div>
  );
}

/** Create or update a record connector, then test it. The field map is driven by GET /records/schema
 * so it always reflects the tenant's real target fields (key / verify / returned / optional). Saving
 * upserts the connector (the returned version bumps on each save); the test calls
 * POST /records/connectors/{id}/test and shows pass/fail. Credentials are sent to the backend, which
 * encrypts them at rest — they are never logged or echoed here. */

import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Plug, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import {
  createConnector,
  testConnector,
  type ConnectorOut,
  type ConnectorTestReport,
  type RecordSchemaOut,
} from "./api";

type SourceType = "upload" | "api" | "db";

const SOURCE_ORDER: SourceType[] = ["upload", "api", "db"];
const SOURCE_LABELS: Record<SourceType, string> = { upload: "Upload", api: "API", db: "Database" };

function titleCase(v: string): string {
  return v.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function TestResult({ report }: { report: ConnectorTestReport }) {
  return (
    <div
      className={cn(
        "space-y-2 rounded-lg border p-3 text-sm",
        report.ok ? "border-success/30 bg-success/10" : "border-destructive/30 bg-destructive/5"
      )}
    >
      <div className="flex items-center gap-2">
        {report.ok ? (
          <CheckCircle2 className="size-4 text-success" />
        ) : (
          <XCircle className="size-4 text-destructive" />
        )}
        <span className={cn("font-medium", report.ok ? "text-success" : "text-destructive")}>
          {report.ok ? "Test passed" : "Test failed"}
        </span>
      </div>
      <ul className="space-y-1 pl-6 text-xs text-muted-foreground">
        <li className="flex items-center gap-1.5">
          {report.found ? (
            <CheckCircle2 className="size-3 text-success" />
          ) : (
            <XCircle className="size-3 text-destructive" />
          )}
          Record found
        </li>
        <li className="flex items-center gap-1.5">
          {report.has_verify_field ? (
            <CheckCircle2 className="size-3 text-success" />
          ) : (
            <XCircle className="size-3 text-destructive" />
          )}
          Verify field present
        </li>
      </ul>
      {report.error ? <p className="pl-6 text-xs text-destructive">{report.error}</p> : null}
    </div>
  );
}

export function ConnectorForm({ schemas }: { schemas: RecordSchemaOut[] }) {
  const [recordType, setRecordType] = useState(schemas[0]?.record_type ?? "");
  const [sourceType, setSourceType] = useState<SourceType>("api");
  const [baseUrl, setBaseUrl] = useState("");
  const [credentials, setCredentials] = useState("");
  const [queryTemplate, setQueryTemplate] = useState("SELECT * FROM records WHERE id = :key");
  const [fieldMap, setFieldMap] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<ConnectorOut | null>(null);
  const [testKey, setTestKey] = useState("");
  const [testReport, setTestReport] = useState<ConnectorTestReport | null>(null);

  const currentSchema = useMemo(
    () => schemas.find((s) => s.record_type === recordType),
    [schemas, recordType]
  );

  const targetFields = useMemo(() => {
    const seen = new Set<string>();
    const out: { field: string; role: string }[] = [];
    const push = (fields: string[] | undefined, role: string) => {
      for (const f of fields ?? []) {
        if (f && !seen.has(f)) {
          seen.add(f);
          out.push({ field: f, role });
        }
      }
    };
    push(currentSchema ? [currentSchema.key] : [], "key");
    push(currentSchema?.alias_keys, "alias");
    push(currentSchema?.verify_fields, "verify");
    push(currentSchema?.returned_fields, "field");
    push(currentSchema?.optional_fields, "optional");
    return out;
  }, [currentSchema]);

  const resetResult = () => {
    setSaved(null);
    setTestReport(null);
  };

  const save = useMutation({
    mutationFn: () => {
      const map: Record<string, string> = {};
      for (const [schemaField, sourceCol] of Object.entries(fieldMap)) {
        const col = sourceCol.trim();
        if (col) map[col] = schemaField; // source column -> schema field
      }
      const config =
        sourceType === "api"
          ? { base_url: baseUrl.trim() }
          : sourceType === "db"
            ? { query_template: queryTemplate.trim() }
            : {};
      return createConnector({
        record_type: recordType,
        source_type: sourceType,
        credentials: sourceType === "upload" ? "" : credentials,
        config,
        field_map: map,
      });
    },
    onSuccess: (c) => {
      setSaved(c);
      setTestReport(null);
      toast.success(`Connector saved (v${c.version}).`);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const test = useMutation({
    mutationFn: () => testConnector(saved!.id, testKey.trim()),
    onSuccess: (r) => {
      setTestReport(r);
      if (r.ok) toast.success("Connector test passed.");
      else toast.error(r.error ?? "Connector test failed.");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const needsBaseUrl = sourceType === "api";
  const needsCredentials = sourceType !== "upload";
  const saveDisabled =
    !recordType ||
    save.isPending ||
    (needsBaseUrl && !baseUrl.trim()) ||
    (needsCredentials && !credentials.trim());

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground">
            <Plug className="size-4" />
          </div>
          <div className="space-y-1">
            <CardTitle className="text-base">Connect a live source</CardTitle>
            <CardDescription>
              Pull records on demand from an API or database instead of uploading a file. Map your
              source columns onto the record schema, then run a test lookup to confirm it works.
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="connector-record-type">Record type</Label>
            <Select
              value={recordType}
              onValueChange={(v) => {
                setRecordType(v);
                setFieldMap({});
                resetResult();
              }}
            >
              <SelectTrigger id="connector-record-type" className="w-full">
                <SelectValue placeholder="Select a record type" />
              </SelectTrigger>
              <SelectContent>
                {schemas.map((s) => (
                  <SelectItem key={s.record_type} value={s.record_type}>
                    {titleCase(s.record_type)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="connector-source-type">Source type</Label>
            <Select
              value={sourceType}
              onValueChange={(v) => {
                setSourceType(v as SourceType);
                resetResult();
              }}
            >
              <SelectTrigger id="connector-source-type" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SOURCE_ORDER.map((s) => (
                  <SelectItem key={s} value={s}>
                    {SOURCE_LABELS[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {sourceType === "upload" ? (
          <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
            An upload connector serves records from a dataset you upload here in the console — no
            connection details are needed. Just map your columns to the schema fields below.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {needsBaseUrl ? (
              <div className="space-y-2">
                <Label htmlFor="connector-base-url">Base URL</Label>
                <Input
                  id="connector-base-url"
                  placeholder="https://api.example.com/v1"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </div>
            ) : null}
            <div className="space-y-2">
              <Label htmlFor="connector-credentials">
                {sourceType === "db" ? "Connection string (DSN)" : "API auth secret"}
              </Label>
              <Input
                id="connector-credentials"
                type="password"
                autoComplete="off"
                placeholder={
                  sourceType === "db"
                    ? "postgresql://user:pass@host/db"
                    : "Bearer token or API key"
                }
                value={credentials}
                onChange={(e) => setCredentials(e.target.value)}
              />
            </div>
          </div>
        )}

        {sourceType === "db" ? (
          <div className="space-y-2">
            <Label htmlFor="connector-query">Query template</Label>
            <Textarea
              id="connector-query"
              rows={2}
              className="font-mono text-xs"
              value={queryTemplate}
              onChange={(e) => setQueryTemplate(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Use <code className="rounded bg-muted px-1 py-0.5 font-mono">:key</code> for the lookup
              value bound at query time.
            </p>
          </div>
        ) : null}

        <Separator />

        <div className="space-y-3">
          <div className="space-y-0.5">
            <Label>Field map</Label>
            <p className="text-xs text-muted-foreground">
              For each schema field, enter the matching column your source returns. Leave a field
              blank to skip it.
            </p>
          </div>
          {targetFields.length === 0 ? (
            <p className="text-sm text-muted-foreground">Select a record type to map its fields.</p>
          ) : (
            <div className="space-y-2">
              {targetFields.map(({ field, role }) => (
                <div
                  key={field}
                  className="grid grid-cols-1 items-center gap-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]"
                >
                  <div className="flex items-center gap-2">
                    <span className="truncate font-mono text-sm">{field}</span>
                    <Badge
                      variant="outline"
                      className="shrink-0 text-[10px] font-normal tracking-wide uppercase"
                    >
                      {role}
                    </Badge>
                  </div>
                  <span className="hidden text-xs text-muted-foreground sm:inline">←</span>
                  <Input
                    aria-label={`Source column for ${field}`}
                    placeholder="source column"
                    value={fieldMap[field] ?? ""}
                    onChange={(e) => setFieldMap((m) => ({ ...m, [field]: e.target.value }))}
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={saveDisabled} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : saved ? "Save changes" : "Save connector"}
          </Button>
          {saved ? (
            <Badge variant="secondary" className="tabular-nums">
              {titleCase(saved.source_type)} · v{saved.version}
            </Badge>
          ) : null}
        </div>

        {saved ? (
          <>
            <Separator />
            <div className="space-y-3">
              <div className="space-y-0.5">
                <Label htmlFor="connector-test-key">Test the connection</Label>
                <p className="text-xs text-muted-foreground">
                  Enter a known lookup value to confirm the connector can fetch and shape a record.
                </p>
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <Input
                  id="connector-test-key"
                  className="max-w-xs"
                  placeholder="e.g. an existing order id"
                  value={testKey}
                  onChange={(e) => setTestKey(e.target.value)}
                />
                <Button
                  variant="outline"
                  disabled={!testKey.trim() || test.isPending}
                  onClick={() => test.mutate()}
                >
                  {test.isPending ? "Testing…" : "Run test"}
                </Button>
              </div>
              {testReport ? <TestResult report={testReport} /> : null}
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

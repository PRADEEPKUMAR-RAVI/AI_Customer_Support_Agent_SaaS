/** Config-driven connector form. The visible fields change with the selected source type, DB
 * dialect, and API auth type — all driven by a declarative schema rather than nested conditionals.
 * Builds the connector `config` (non-secret) + a single `credentials` secret + `field_map`, then
 * either creates (upsert) or patches. "Validate" runs a test-before-save lookup that persists
 * nothing. Secrets are sent to the backend (encrypted at rest) and never echoed here. */

import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Plug, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  patchConnector,
  validateConnector,
  type ConnectorDetail,
  type ConnectorTestReport,
  type RecordSchemaOut,
} from "./api";

type SourceType = "db" | "api";
type Dialect = "postgresql" | "mysql" | "mssql" | "oracle" | "sqlite";
type ConnMode = "guided" | "dsn";
type AuthType = "none" | "api_key" | "bearer" | "basic" | "oauth2_client_credentials";

// PostgreSQL is self-serve today. The others aren't disabled because they're unbuilt — the resolver
// is dialect-agnostic — but because each needs its driver enabled per deployment, so they're offered
// as "configurable on request" rather than a click-and-connect option.
const DIALECTS: { value: Dialect; label: string; port: string; enabled: boolean }[] = [
  { value: "postgresql", label: "PostgreSQL", port: "5432", enabled: true },
  { value: "mysql", label: "MySQL / MariaDB", port: "3306", enabled: false },
  { value: "mssql", label: "SQL Server", port: "1433", enabled: false },
  { value: "oracle", label: "Oracle", port: "1521", enabled: false },
  { value: "sqlite", label: "SQLite", port: "", enabled: false },
];

const AUTH_TYPES: { value: AuthType; label: string }[] = [
  { value: "none", label: "No auth" },
  { value: "api_key", label: "API key" },
  { value: "bearer", label: "Bearer token" },
  { value: "basic", label: "Basic auth" },
  { value: "oauth2_client_credentials", label: "OAuth 2.0 (client credentials)" },
];

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
            <XCircle className="size-3 text-muted-foreground" />
          )}
          {report.found ? "Record found" : "Reachable — that key wasn't present"}
        </li>
        {report.found ? (
          <li className="flex items-center gap-1.5">
            {report.has_verify_field ? (
              <CheckCircle2 className="size-3 text-success" />
            ) : (
              <XCircle className="size-3 text-destructive" />
            )}
            Verify field present
          </li>
        ) : null}
      </ul>
      {report.error ? <p className="pl-6 text-xs text-destructive">{report.error}</p> : null}
    </div>
  );
}

export function ConnectorForm({
  schemas,
  existing,
  onSaved,
}: {
  schemas: RecordSchemaOut[];
  existing?: ConnectorDetail | null;
  onSaved: () => void;
}) {
  const editing = !!existing;

  const [recordType, setRecordType] = useState(existing?.record_type ?? schemas[0]?.record_type ?? "");
  const [sourceType, setSourceType] = useState<SourceType>((existing?.source_type as SourceType) ?? "api");

  // db
  const [dialect, setDialect] = useState<Dialect>("postgresql");
  const [connMode, setConnMode] = useState<ConnMode>("guided");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("5432");
  const [database, setDatabase] = useState("");
  const [username, setUsername] = useState("");
  const [queryTemplate, setQueryTemplate] = useState(
    "SELECT * FROM orders WHERE order_id = :key"
  );

  // api
  const [baseUrl, setBaseUrl] = useState("");
  const [method, setMethod] = useState("GET");
  const [pathTemplate, setPathTemplate] = useState("/{key}");
  const [authType, setAuthType] = useState<AuthType>("bearer");
  const [apiKeyIn, setApiKeyIn] = useState<"header" | "query">("header");
  const [apiKeyName, setApiKeyName] = useState("X-API-Key");
  const [basicUser, setBasicUser] = useState("");
  const [oauthTokenUrl, setOauthTokenUrl] = useState("");
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthScope, setOauthScope] = useState("");
  const [responsePath, setResponsePath] = useState("");

  const [credentials, setCredentials] = useState("");
  const [fieldMap, setFieldMap] = useState<Record<string, string>>({});
  const [testKey, setTestKey] = useState("");
  const [report, setReport] = useState<ConnectorTestReport | null>(null);

  // Hydrate the form from an existing connector's (masked) config + field map when editing.
  useEffect(() => {
    if (!existing) return;
    const cfg = (existing.config ?? {}) as Record<string, unknown>;
    const str = (v: unknown, d = "") => (typeof v === "string" ? v : v == null ? d : String(v));
    if (existing.source_type === "db") {
      setDialect((str(cfg.dialect, "postgresql") as Dialect) || "postgresql");
      setConnMode(cfg.host ? "guided" : "dsn");
      setHost(str(cfg.host));
      setPort(str(cfg.port, "5432"));
      setDatabase(str(cfg.database));
      setUsername(str(cfg.username));
      setQueryTemplate(str(cfg.query_template, queryTemplate));
    } else {
      setBaseUrl(str(cfg.base_url));
      setMethod(str(cfg.method, "GET"));
      setPathTemplate(str(cfg.path_template, "/{key}"));
      setResponsePath(str(cfg.response_path));
      const auth = (cfg.auth ?? {}) as Record<string, unknown>;
      setAuthType((str(auth.type, "none") as AuthType) || "none");
      setApiKeyIn((str(auth.in, "header") as "header" | "query") || "header");
      setApiKeyName(str(auth.name, "X-API-Key"));
      setBasicUser(str(auth.username));
      setOauthTokenUrl(str(auth.token_url));
      setOauthClientId(str(auth.client_id));
      setOauthScope(str(auth.scope));
    }
    // Invert stored {source: schemaField} back to the form's {schemaField: source}.
    const fm: Record<string, string> = {};
    for (const [src, sf] of Object.entries(existing.field_map ?? {})) fm[sf as string] = src;
    setFieldMap(fm);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing]);

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

  const verifyFields = useMemo(
    () => new Set(currentSchema?.verify_fields ?? []),
    [currentSchema]
  );
  const verifyMapped = Object.entries(fieldMap).some(
    ([sf, col]) => verifyFields.has(sf) && col.trim()
  );

  function buildPayload() {
    const field_map: Record<string, string> = {};
    for (const [schemaField, sourceCol] of Object.entries(fieldMap)) {
      const col = sourceCol.trim();
      if (col) field_map[col] = schemaField; // source column -> schema field
    }
    let config: Record<string, unknown>;
    if (sourceType === "db") {
      config = { dialect, query_template: queryTemplate.trim() };
      if (connMode === "guided") {
        config.host = host.trim();
        config.port = Number(port) || undefined;
        config.database = database.trim();
        config.username = username.trim();
      }
    } else {
      const auth: Record<string, unknown> = { type: authType };
      if (authType === "api_key") {
        auth.in = apiKeyIn;
        auth.name = apiKeyName.trim();
      } else if (authType === "basic") {
        auth.username = basicUser.trim();
      } else if (authType === "oauth2_client_credentials") {
        auth.token_url = oauthTokenUrl.trim();
        auth.client_id = oauthClientId.trim();
        if (oauthScope.trim()) auth.scope = oauthScope.trim();
      }
      config = { base_url: baseUrl.trim(), method, path_template: pathTemplate.trim(), auth };
      if (responsePath.trim()) config.response_path = responsePath.trim();
    }
    return { config, credentials, field_map };
  }

  const save = useMutation({
    mutationFn: async () => {
      const { config, credentials: secret, field_map } = buildPayload();
      if (editing && existing) {
        const body: import("./api").ConnectorPatchIn = { config, field_map };
        if (secret.trim()) body.credentials = secret; // only rotate when a new secret was entered
        return patchConnector(existing.id, body);
      }
      return createConnector({
        record_type: recordType,
        source_type: sourceType,
        credentials: secret,
        config,
        field_map,
      });
    },
    onSuccess: () => {
      toast.success(editing ? "Connector updated" : "Connector saved");
      onSaved();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Save failed"),
  });

  const validate = useMutation({
    mutationFn: async () => {
      const { config, credentials: secret, field_map } = buildPayload();
      return validateConnector({
        record_type: recordType,
        source_type: sourceType,
        credentials: secret,
        config,
        field_map,
        test_key: testKey.trim(),
      });
    },
    onSuccess: (r) => {
      setReport(r);
      if (r.ok) toast.success("Test passed");
      else toast.error(r.error ?? "Test failed");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Test failed"),
  });

  const dialectMeta = DIALECTS.find((d) => d.value === dialect);
  const secretPlaceholder = editing ? "Leave blank to keep current secret" : "•••••••••";

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="cf-record-type">Record type</Label>
          <Select value={recordType} onValueChange={setRecordType} disabled={editing}>
            <SelectTrigger id="cf-record-type" className="w-full">
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
          <Label htmlFor="cf-source-type">Source type</Label>
          <Select
            value={sourceType}
            onValueChange={(v) => {
              setSourceType(v as SourceType);
              setReport(null);
            }}
            disabled={editing}
          >
            <SelectTrigger id="cf-source-type" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="db">Database</SelectItem>
              <SelectItem value="api">API</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Separator />

      {/* ── DATABASE ── */}
      {sourceType === "db" ? (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="cf-dialect">Database</Label>
              <Select value={dialect} onValueChange={(v) => setDialect(v as Dialect)}>
                <SelectTrigger id="cf-dialect" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DIALECTS.map((d) => (
                    <SelectItem key={d.value} value={d.value} disabled={!d.enabled}>
                      {d.label}
                      {d.enabled ? "" : " — configurable on request"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="cf-conn-mode">Connection details</Label>
              <Select value={connMode} onValueChange={(v) => setConnMode(v as ConnMode)}>
                <SelectTrigger id="cf-conn-mode" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="guided">Guided (host, port…)</SelectItem>
                  <SelectItem value="dsn">Paste connection string</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            PostgreSQL works out of the box. Any other database — MySQL, SQL Server, Oracle, and more —
            can be configured for your workspace; ask us to enable it for your deployment.
          </p>

          {connMode === "guided" ? (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="cf-host">Host</Label>
                  <Input
                    id="cf-host"
                    placeholder="db.internal.example.com"
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cf-port">Port</Label>
                  <Input
                    id="cf-port"
                    inputMode="numeric"
                    placeholder={dialectMeta?.port}
                    value={port}
                    onChange={(e) => setPort(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="cf-database">Database</Label>
                  <Input id="cf-database" value={database} onChange={(e) => setDatabase(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cf-username">Username</Label>
                  <Input
                    id="cf-username"
                    placeholder="readonly_svc"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cf-secret-db">Password</Label>
                  <Input
                    id="cf-secret-db"
                    type="password"
                    autoComplete="off"
                    placeholder={secretPlaceholder}
                    value={credentials}
                    onChange={(e) => setCredentials(e.target.value)}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="cf-dsn">Connection string (DSN)</Label>
              <Input
                id="cf-dsn"
                type="password"
                autoComplete="off"
                placeholder={editing ? secretPlaceholder : "postgresql://user:pass@host:5432/db"}
                value={credentials}
                onChange={(e) => setCredentials(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                The driver is normalized automatically. Use read-only credentials.
              </p>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="cf-query">Query template</Label>
            <Textarea
              id="cf-query"
              rows={2}
              className="font-mono text-xs"
              value={queryTemplate}
              onChange={(e) => setQueryTemplate(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Bind the lookup value with <code className="rounded bg-muted px-1 py-0.5 font-mono">:key</code>.
              Read-only <code className="rounded bg-muted px-1 py-0.5 font-mono">SELECT</code> only.
            </p>
          </div>
        </div>
      ) : (
        /* ── API ── */
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="cf-base-url">Base URL</Label>
              <Input
                id="cf-base-url"
                placeholder="https://api.example.com/v1"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cf-method">Method</Label>
              <Select value={method} onValueChange={setMethod}>
                <SelectTrigger id="cf-method" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="GET">GET</SelectItem>
                  <SelectItem value="POST">POST</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="cf-path">Path template</Label>
            <Input id="cf-path" value={pathTemplate} onChange={(e) => setPathTemplate(e.target.value)} />
            <p className="text-xs text-muted-foreground">
              Appended to the base URL. Insert the lookup value with{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono">{"{key}"}</code>.
            </p>
          </div>

          <div className="space-y-2 sm:max-w-xs">
            <Label htmlFor="cf-auth">Authorization</Label>
            <Select value={authType} onValueChange={(v) => setAuthType(v as AuthType)}>
              <SelectTrigger id="cf-auth" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AUTH_TYPES.map((a) => (
                  <SelectItem key={a.value} value={a.value}>
                    {a.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {authType === "api_key" ? (
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="cf-ak-in">Add to</Label>
                <Select value={apiKeyIn} onValueChange={(v) => setApiKeyIn(v as "header" | "query")}>
                  <SelectTrigger id="cf-ak-in" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="header">Header</SelectItem>
                    <SelectItem value="query">Query param</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="cf-ak-name">Name</Label>
                <Input id="cf-ak-name" value={apiKeyName} onChange={(e) => setApiKeyName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cf-ak-value">Value</Label>
                <Input
                  id="cf-ak-value"
                  type="password"
                  autoComplete="off"
                  placeholder={secretPlaceholder}
                  value={credentials}
                  onChange={(e) => setCredentials(e.target.value)}
                />
              </div>
            </div>
          ) : null}

          {authType === "bearer" ? (
            <div className="space-y-2">
              <Label htmlFor="cf-bearer">Token</Label>
              <Input
                id="cf-bearer"
                type="password"
                autoComplete="off"
                placeholder={secretPlaceholder}
                value={credentials}
                onChange={(e) => setCredentials(e.target.value)}
              />
            </div>
          ) : null}

          {authType === "basic" ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="cf-basic-user">Username</Label>
                <Input id="cf-basic-user" value={basicUser} onChange={(e) => setBasicUser(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cf-basic-pass">Password</Label>
                <Input
                  id="cf-basic-pass"
                  type="password"
                  autoComplete="off"
                  placeholder={secretPlaceholder}
                  value={credentials}
                  onChange={(e) => setCredentials(e.target.value)}
                />
              </div>
            </div>
          ) : null}

          {authType === "oauth2_client_credentials" ? (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="cf-oauth-url">Token URL</Label>
                <Input
                  id="cf-oauth-url"
                  placeholder="https://auth.example.com/oauth/token"
                  value={oauthTokenUrl}
                  onChange={(e) => setOauthTokenUrl(e.target.value)}
                />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="cf-oauth-id">Client ID</Label>
                  <Input id="cf-oauth-id" value={oauthClientId} onChange={(e) => setOauthClientId(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cf-oauth-secret">Client secret</Label>
                  <Input
                    id="cf-oauth-secret"
                    type="password"
                    autoComplete="off"
                    placeholder={secretPlaceholder}
                    value={credentials}
                    onChange={(e) => setCredentials(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-2 sm:max-w-sm">
                <Label htmlFor="cf-oauth-scope">
                  Scope <span className="font-normal text-muted-foreground">(optional)</span>
                </Label>
                <Input id="cf-oauth-scope" value={oauthScope} onChange={(e) => setOauthScope(e.target.value)} />
              </div>
            </div>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="cf-response-path">
              Response path <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="cf-response-path"
              placeholder="data.order"
              value={responsePath}
              onChange={(e) => setResponsePath(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Where the record sits in the response, e.g.{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono">data.order</code>. Blank = top level.
            </p>
          </div>
        </div>
      )}

      <Separator />

      {/* ── FIELD MAP ── */}
      <div className="space-y-3">
        <div className="space-y-0.5">
          <Label>Field map</Label>
          <p className="text-xs text-muted-foreground">
            For each schema field, name the matching {sourceType === "db" ? "column" : "response field"}
            {" "}your source returns. The verify field is required.
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
                  <Badge variant="outline" className="shrink-0 text-[10px] font-normal tracking-wide uppercase">
                    {role}
                  </Badge>
                </div>
                <span className="hidden text-xs text-muted-foreground sm:inline">←</span>
                <Input
                  aria-label={`Source for ${field}`}
                  placeholder="source column"
                  value={fieldMap[field] ?? ""}
                  onChange={(e) => setFieldMap((m) => ({ ...m, [field]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        )}
        {!verifyMapped && targetFields.length > 0 ? (
          <p className="text-xs text-warning-foreground">
            Map a source field onto the verify field before saving — a connector that can't return it
            can't back a verified record type.
          </p>
        ) : null}
      </div>

      <Separator />

      {/* ── VALIDATE (test-before-save) ── */}
      <div className="space-y-2">
        <Label htmlFor="cf-test-key">Test the connection</Label>
        <p className="text-xs text-muted-foreground">
          Enter a known lookup value to confirm the connector fetches and shapes a record — nothing is
          saved.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <Input
            id="cf-test-key"
            className="max-w-xs"
            placeholder="e.g. an existing order id"
            value={testKey}
            onChange={(e) => setTestKey(e.target.value)}
          />
          <Button
            variant="outline"
            disabled={!testKey.trim() || validate.isPending}
            onClick={() => validate.mutate()}
          >
            {validate.isPending ? "Testing…" : "Validate"}
          </Button>
        </div>
        {report ? <TestResult report={report} /> : null}
      </div>

      <div className="flex items-center gap-2">
        <Button disabled={!recordType || save.isPending} onClick={() => save.mutate()}>
          <Plug className="size-4" />
          {save.isPending ? "Saving…" : editing ? "Save changes" : "Save connector"}
        </Button>
        {!editing ? (
          <p className="text-xs text-muted-foreground">
            Added paused if this record type already has an active source — activate it from the list.
          </p>
        ) : null}
      </div>
    </div>
  );
}

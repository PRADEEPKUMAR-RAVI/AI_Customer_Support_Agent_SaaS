/** FE-Onboarding — the guided setup wizard.
 *
 * An eight-step, server-resumable stepper: industry -> record templates -> knowledge ->
 * records -> agent config -> allowed domains -> invite staff -> embed snippet. Industry itself
 * is chosen at signup (the backend's `SignupRequest` requires it), so step 1 confirms rather than
 * edits it — there is no endpoint to change a tenant's industry.
 *
 * "Resumable from server state": every step derives its own completion from the API (uploaded
 * sources, datasets, saved config, allowed domains, invited staff), so returning to onboarding
 * re-hydrates progress and jumps to the first incomplete step. All step queries are keyed to the
 * shared resource caches, so work done here is reflected on the dedicated Knowledge/Records/Staff
 * pages and vice-versa.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  ClipboardType,
  Code2,
  Copy,
  Download,
  FileText,
  Globe,
  Link2,
  MessageSquare,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
  UserPlus,
  Users,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { api, unwrap } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { cn } from "@/lib/utils";
import type { components } from "@/api/generated/schema";
import { RECORD_TYPES_BY_INDUSTRY } from "./recordTypes";

type Tenant = components["schemas"]["TenantResponse"];
type AgentSettings = components["schemas"]["AgentSettingsResponse"];
type SourceOut = components["schemas"]["SourceOut"];
type DatasetOut = components["schemas"]["DatasetOut"];
type UploadReport = components["schemas"]["DatasetUploadReport"];
type AllowedDomain = components["schemas"]["AllowedDomainResponse"];
type Staff = components["schemas"]["StaffResponse"];
type EmbedSnippet = components["schemas"]["EmbedSnippetResponse"];

type StepKey =
  | "industry"
  | "templates"
  | "knowledge"
  | "records"
  | "config"
  | "domains"
  | "staff"
  | "embed";

const STEPS: {
  key: StepKey;
  label: string;
  hint: string;
  description: string;
  icon: typeof Building2;
}[] = [
  {
    key: "industry",
    label: "Industry",
    hint: "Your vertical",
    description: "Confirm the industry your workspace was created for — it decides which record types your agent understands.",
    icon: Building2,
  },
  {
    key: "templates",
    label: "Record templates",
    hint: "Download CSVs",
    description: "Download a CSV template for each record type, fill it with your own customer data, then upload it in the Customer records step.",
    icon: FileText,
  },
  {
    key: "knowledge",
    label: "Knowledge base",
    hint: "Docs, FAQs & URLs",
    description: "Add the documents, FAQs, and pages the agent should ground its answers in. Sources are chunked and indexed after upload.",
    icon: MessageSquare,
  },
  {
    key: "records",
    label: "Customer records",
    hint: "Upload datasets",
    description: "Upload the filled-in templates so the agent can look up and verify orders, shipments, appointments and more.",
    icon: Upload,
  },
  {
    key: "config",
    label: "Agent configuration",
    hint: "Persona & escalation",
    description: "Set your agent's voice, greeting, language, and the triggers that hand a conversation to a human.",
    icon: MessageSquare,
  },
  {
    key: "domains",
    label: "Allowed domains",
    hint: "Where it runs",
    description: "Whitelist the sites permitted to embed your chat widget. Requests from other origins are refused.",
    icon: Globe,
  },
  {
    key: "staff",
    label: "Invite your team",
    hint: "Agents & admins",
    description: "Invite teammates who will handle escalated conversations or manage the workspace.",
    icon: Users,
  },
  {
    key: "embed",
    label: "Embed the widget",
    hint: "Go live",
    description: "Drop the snippet onto your site and you're live. Copy it, add the CSP rules if you enforce one, and ship.",
    icon: Code2,
  },
];

// Mirrors `app/domain/escalation/reasons.py::EscalationReason` for display only — the backend
// is the source of truth and validates independently of what this checklist shows.
const ESCALATION_TRIGGERS = [
  { value: "no_grounding", label: "No grounded answer found" },
  { value: "explicit", label: "Customer explicitly asks for a human" },
  { value: "sensitive", label: "Sensitive-intent keyword match" },
  { value: "dispute", label: "Deterministic record-state dispute" },
  { value: "n_fails", label: "Repeated verification failures" },
  { value: "proactive", label: "Customer accepts a proactive human offer" },
  { value: "timeout", label: "Per-turn timeout" },
];

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "hi", label: "Hindi" },
];

const INDUSTRY_LABELS: Record<string, string> = {
  retail: "Retail / E-commerce",
  logistics: "Logistics / Courier",
  telecom: "Telecom / ISP",
  healthcare: "Healthcare / Clinic",
  travel: "Travel / Hospitality",
};

// Tenant staff roles (mirrors `lib/rbac.ts` — `platform` is operator-only, not invitable here).
const STAFF_ROLES = [
  { value: "agent", label: "Agent" },
  { value: "admin", label: "Admin" },
];

// ── shared query hooks (keys aligned to sibling pages so caches stay in sync) ────────────────

function useTenant() {
  return useQuery({
    queryKey: ["tenant"],
    queryFn: async () => unwrap<Tenant>(await api.GET("/api/v1/admin/tenant")),
  });
}

function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: async () => unwrap<AgentSettings>(await api.GET("/api/v1/admin/settings")),
  });
}

function useSources() {
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

function useDatasets() {
  return useQuery({
    queryKey: ["records", "datasets"],
    queryFn: async () => unwrap<DatasetOut[]>(await api.GET("/api/v1/records/datasets")),
  });
}

function useDomains() {
  return useQuery({
    queryKey: ["admin", "allowed-domains"],
    queryFn: async () => unwrap<AllowedDomain[]>(await api.GET("/api/v1/admin/allowed-domains")),
  });
}

function useStaff() {
  return useQuery({
    queryKey: ["admin", "staff"],
    queryFn: async () => unwrap<Staff[]>(await api.GET("/api/v1/admin/staff")),
  });
}

function useEmbed() {
  return useQuery({
    queryKey: ["embed-snippet"],
    queryFn: async () => unwrap<EmbedSnippet>(await api.GET("/api/v1/admin/embed-snippet")),
  });
}

// ── helpers ─────────────────────────────────────────────────────────────────────────────────

function asStr(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function asStrArr(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

function errMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

async function downloadTemplate(recordType: string): Promise<void> {
  const token = getAccessToken();
  const res = await fetch(`/api/v1/records/templates/${recordType}?format=csv`, {
    headers: token ? { authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    toast.error("Couldn't download template", { description: `Server returned ${res.status}.` });
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${recordType}_template.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── step 1: industry ─────────────────────────────────────────────────────────────────────────

function IndustryStep({ tenant }: { tenant: Tenant }) {
  const label = INDUSTRY_LABELS[tenant.industry] ?? tenant.industry;
  const recordTypes = RECORD_TYPES_BY_INDUSTRY[tenant.industry] ?? [];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/40 px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
            <Building2 className="size-5" />
          </div>
          <div>
            <p className="text-sm font-medium">{label}</p>
            <p className="text-xs text-muted-foreground">{tenant.name}</p>
          </div>
        </div>
        <StatusBadge value="ready" />
      </div>
      <p className="text-sm text-muted-foreground">
        Your industry was locked in when the workspace was created and can't be changed here — it
        provisions the record schema and default agent behaviour. This vertical supports these
        record types:
      </p>
      <div className="flex flex-wrap gap-2">
        {recordTypes.length ? (
          recordTypes.map((rt) => (
            <span
              key={rt}
              className="inline-flex items-center gap-1.5 rounded-md border bg-card px-2.5 py-1 text-xs font-medium capitalize"
            >
              <FileText className="size-3.5 text-muted-foreground" />
              {rt}
            </span>
          ))
        ) : (
          <p className="text-sm text-muted-foreground">No record types registered for this industry.</p>
        )}
      </div>
    </div>
  );
}

// ── step 2: templates ────────────────────────────────────────────────────────────────────────

function TemplatesStep({ industry }: { industry: string }) {
  const recordTypes = RECORD_TYPES_BY_INDUSTRY[industry] ?? [];
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Download a template per record type, fill each with your own customer data, and upload the
        files in the <span className="font-medium text-foreground">Customer records</span> step.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {recordTypes.map((rt) => (
          <div
            key={rt}
            className="flex items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3"
          >
            <div className="flex items-center gap-3">
              <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground">
                <FileText className="size-4" />
              </div>
              <div>
                <p className="text-sm font-medium capitalize">{rt}</p>
                <p className="text-xs text-muted-foreground">CSV template</p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => void downloadTemplate(rt)}>
              <Download className="size-4" />
              Download
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── step 3: knowledge ────────────────────────────────────────────────────────────────────────

type KnowledgeKind = "file" | "url" | "paste";

function KnowledgeStep() {
  const qc = useQueryClient();
  const { data: sources, isLoading, isError, refetch } = useSources();
  const [kind, setKind] = useState<KnowledgeKind>("file");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [content, setContent] = useState("");

  const invalidate = () => void qc.invalidateQueries({ queryKey: ["kb", "sources"] });

  const add = useMutation({
    mutationFn: async () => {
      if (kind === "file") {
        if (!file) throw new Error("Choose a file to upload.");
        const displayName = name.trim();
        return unwrap<SourceOut>(
          await api.POST("/api/v1/knowledge/sources/file", {
            // Body typed to the multipart schema; the serializer emits the real FormData.
            body: { file: file as unknown as string, name: displayName || null },
            bodySerializer() {
              const form = new FormData();
              form.append("file", file);
              if (displayName) form.append("name", displayName);
              return form;
            },
          })
        );
      }
      if (kind === "url") {
        return unwrap(
          await api.POST("/api/v1/knowledge/sources/url", {
            body: { name: name.trim() || url.trim(), url: url.trim() },
          })
        );
      }
      return unwrap(
        await api.POST("/api/v1/knowledge/sources/paste", {
          body: { name: name.trim() || "Pasted note", content },
        })
      );
    },
    onSuccess: () => {
      toast.success("Source added", { description: "It will be indexed shortly." });
      setFile(null);
      setName("");
      setUrl("");
      setContent("");
      invalidate();
    },
    onError: (err) => toast.error("Couldn't add source", { description: errMessage(err, "Try again.") }),
  });

  return (
    <div className="space-y-6">
      <div className="space-y-4 rounded-xl border bg-muted/30 p-4">
        <div className="grid gap-2 sm:max-w-xs">
          <Label htmlFor="kb-kind">Source type</Label>
          <Select value={kind} onValueChange={(v) => setKind(v as KnowledgeKind)}>
            <SelectTrigger id="kb-kind" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="file">Upload a file</SelectItem>
              <SelectItem value="url">Import from URL</SelectItem>
              <SelectItem value="paste">Paste text</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {kind === "file" && (
          <div className="grid gap-2">
            <Label htmlFor="kb-file">File</Label>
            <Input
              id="kb-file"
              type="file"
              accept=".pdf,.txt,.md,.csv,.html,.docx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
        )}

        {kind === "url" && (
          <div className="grid gap-2">
            <Label htmlFor="kb-url">Page URL</Label>
            <Input
              id="kb-url"
              type="url"
              placeholder="https://help.example.com/returns"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
        )}

        {kind === "paste" && (
          <div className="grid gap-2">
            <Label htmlFor="kb-content">Content</Label>
            <Textarea
              id="kb-content"
              rows={5}
              placeholder="Paste an FAQ, policy, or any text the agent should know…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
        )}

        <div className="grid gap-2">
          <Label htmlFor="kb-name">
            Display name <span className="font-normal text-muted-foreground">(optional)</span>
          </Label>
          <Input
            id="kb-name"
            placeholder="Returns policy"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <Button onClick={() => add.mutate()} disabled={add.isPending}>
          {kind === "url" ? (
            <Link2 className="size-4" />
          ) : kind === "paste" ? (
            <ClipboardType className="size-4" />
          ) : (
            <Upload className="size-4" />
          )}
          {add.isPending ? "Adding…" : "Add source"}
        </Button>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-medium">Existing sources</h3>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full rounded-lg" />
            <Skeleton className="h-14 w-full rounded-lg" />
          </div>
        ) : isError ? (
          <ErrorState message="Couldn't load your knowledge sources." onRetry={() => void refetch()} />
        ) : !sources?.length ? (
          <EmptyState
            icon={MessageSquare}
            title="No sources yet"
            description="Add your first document, FAQ, or URL above to ground the agent's answers."
          />
        ) : (
          <ul className="divide-y rounded-xl border bg-card">
            {sources.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{s.name}</p>
                  <p className="text-xs text-muted-foreground">
                    <span className="capitalize">{s.kind}</span>
                    {s.chunk_count > 0 && (
                      <>
                        {" · "}
                        <span className="tabular-nums">{s.chunk_count}</span> chunks
                      </>
                    )}
                  </p>
                </div>
                <StatusBadge value={s.status} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ── step 4: records ──────────────────────────────────────────────────────────────────────────

function RecordsStep({ industry }: { industry: string }) {
  const qc = useQueryClient();
  const recordTypes = RECORD_TYPES_BY_INDUSTRY[industry] ?? [];
  const { data: datasets, isLoading, isError, refetch } = useDatasets();
  const [recordType, setRecordType] = useState<string>(recordTypes[0] ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<UploadReport | null>(null);

  const upload = useMutation({
    mutationFn: async () => {
      if (!recordType) throw new Error("Pick a record type.");
      if (!file) throw new Error("Choose a CSV file to upload.");
      return unwrap<UploadReport>(
        await api.POST("/api/v1/records/datasets", {
          // Body typed to the multipart schema; the serializer emits the real FormData.
          body: { record_type: recordType, file: file as unknown as string },
          bodySerializer() {
            const form = new FormData();
            form.append("record_type", recordType);
            form.append("file", file);
            return form;
          },
        })
      );
    },
    onSuccess: (r) => {
      setReport(r);
      setFile(null);
      if (r.ok) {
        toast.success(`Imported ${r.inserted} ${r.record_type} record(s)`);
      } else {
        toast.error("Upload finished with problems", {
          description: "Review the details below and re-upload.",
        });
      }
      void qc.invalidateQueries({ queryKey: ["records", "datasets"] });
    },
    onError: (err) => toast.error("Upload failed", { description: errMessage(err, "Try again.") }),
  });

  return (
    <div className="space-y-6">
      <div className="space-y-4 rounded-xl border bg-muted/30 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="rec-type">Record type</Label>
            <Select value={recordType} onValueChange={setRecordType}>
              <SelectTrigger id="rec-type" className="w-full">
                <SelectValue placeholder="Select a record type" />
              </SelectTrigger>
              <SelectContent>
                {recordTypes.map((rt) => (
                  <SelectItem key={rt} value={rt} className="capitalize">
                    {rt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="rec-file">CSV file</Label>
            <Input
              id="rec-file"
              type="file"
              accept=".csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
        </div>
        <Button onClick={() => upload.mutate()} disabled={upload.isPending}>
          <Upload className="size-4" />
          {upload.isPending ? "Uploading…" : "Upload dataset"}
        </Button>
      </div>

      {report && (
        <div
          className={cn(
            "space-y-2 rounded-xl border p-4 text-sm",
            report.ok ? "border-success/30 bg-success/5" : "border-warning/40 bg-warning/10"
          )}
        >
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium capitalize">{report.record_type} upload</p>
            <StatusBadge value={report.ok ? "ready" : "failed"} />
          </div>
          <p className="text-muted-foreground">
            <span className="tabular-nums">{report.inserted}</span> inserted
            {report.truncated ? (
              <>
                {" · "}
                <span className="tabular-nums">{report.truncated}</span> replaced prior rows
              </>
            ) : null}
          </p>
          {report.missing_headers?.length ? (
            <p className="text-destructive">Missing headers: {report.missing_headers.join(", ")}</p>
          ) : null}
          {report.duplicate_keys?.length ? (
            <p className="text-warning-foreground">
              Duplicate keys: {report.duplicate_keys.slice(0, 5).join(", ")}
              {report.duplicate_keys.length > 5 ? "…" : ""}
            </p>
          ) : null}
          {report.row_errors?.length ? (
            <p className="text-destructive">
              <span className="tabular-nums">{report.row_errors.length}</span> row error(s) — first:
              row {report.row_errors[0].row}, {report.row_errors[0].error}
            </p>
          ) : null}
        </div>
      )}

      <div className="space-y-3">
        <h3 className="text-sm font-medium">Uploaded datasets</h3>
        {isLoading ? (
          <Skeleton className="h-14 w-full rounded-lg" />
        ) : isError ? (
          <ErrorState message="Couldn't load your datasets." onRetry={() => void refetch()} />
        ) : !datasets?.length ? (
          <EmptyState
            icon={Upload}
            title="No datasets yet"
            description="Upload a filled-in template above so the agent can look up customer records."
          />
        ) : (
          <ul className="divide-y rounded-xl border bg-card">
            {datasets.map((d) => (
              <li key={d.record_type} className="flex items-center justify-between gap-3 px-4 py-3">
                <div>
                  <p className="text-sm font-medium capitalize">{d.record_type}</p>
                  <p className="text-xs text-muted-foreground">
                    Updated {new Date(d.updated_at).toLocaleDateString()}
                  </p>
                </div>
                <span className="text-sm text-muted-foreground tabular-nums">
                  {d.row_count.toLocaleString()} rows
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ── step 5: agent config ─────────────────────────────────────────────────────────────────────

const configSchema = z.object({
  persona: z.string(),
  welcome_message: z.string(),
  default_language: z.string(),
  active_triggers: z.array(z.string()),
  sensitive_intent_list: z.string(),
  sla_followup_text: z.string(),
});

type ConfigValues = z.infer<typeof configSchema>;

function ConfigForm({ config }: { config: Record<string, unknown> }) {
  const qc = useQueryClient();

  const form = useForm<ConfigValues>({
    resolver: zodResolver(configSchema),
    defaultValues: {
      persona: asStr(config.persona),
      welcome_message: asStr(config.welcome_message),
      default_language: asStr(config.default_language) || "en",
      active_triggers: Array.isArray(config.active_triggers)
        ? asStrArr(config.active_triggers)
        : ESCALATION_TRIGGERS.map((t) => t.value),
      sensitive_intent_list: asStrArr(config.sensitive_intent_list).join(", "),
      sla_followup_text: asStr(config.sla_followup_text),
    },
  });

  const patch = useMutation({
    mutationFn: async (values: ConfigValues) =>
      unwrap(
        await api.PATCH("/api/v1/admin/settings", {
          body: {
            config: {
              persona: values.persona,
              welcome_message: values.welcome_message,
              default_language: values.default_language,
              active_triggers: values.active_triggers,
              sensitive_intent_list: values.sensitive_intent_list
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
              sla_followup_text: values.sla_followup_text,
            },
          },
        })
      ),
    onSuccess: () => {
      toast.success("Configuration saved");
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err) => toast.error("Couldn't save", { description: errMessage(err, "Try again.") }),
  });

  const triggers = form.watch("active_triggers");
  const toggleTrigger = (value: string, checked: boolean) => {
    const next = checked ? [...triggers, value] : triggers.filter((v) => v !== value);
    form.setValue("active_triggers", next, { shouldDirty: true });
  };

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit((v) => patch.mutate(v))} className="space-y-6">
        <div className="grid gap-5">
          <FormField
            control={form.control}
            name="persona"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Persona</FormLabel>
                <FormControl>
                  <Textarea
                    rows={3}
                    placeholder="A warm, concise support specialist who always cites policy…"
                    {...field}
                  />
                </FormControl>
                <FormDescription>How the agent should sound and behave.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="welcome_message"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Welcome message</FormLabel>
                <FormControl>
                  <Input placeholder="Hi! How can I help you today?" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="default_language"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Default language</FormLabel>
                <Select onValueChange={field.onChange} value={field.value}>
                  <FormControl>
                    <SelectTrigger className="w-full sm:max-w-xs">
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {LANGUAGES.map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        <div className="space-y-3 rounded-xl border p-4">
          <div>
            <p className="text-sm font-medium">Escalation triggers</p>
            <p className="text-xs text-muted-foreground">
              When any active trigger fires, the conversation hands off to a human.
            </p>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {ESCALATION_TRIGGERS.map((t) => (
              <Label
                key={t.value}
                htmlFor={`trigger-${t.value}`}
                className="flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2.5 font-normal"
              >
                <Checkbox
                  id={`trigger-${t.value}`}
                  checked={triggers.includes(t.value)}
                  onCheckedChange={(c) => toggleTrigger(t.value, c === true)}
                />
                <span className="text-sm">{t.label}</span>
              </Label>
            ))}
          </div>
        </div>

        <div className="grid gap-5">
          <FormField
            control={form.control}
            name="sensitive_intent_list"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Sensitive-intent keywords</FormLabel>
                <FormControl>
                  <Input placeholder="lawsuit, chargeback, cancel account" {...field} />
                </FormControl>
                <FormDescription>Comma-separated. A match forces a human hand-off.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="sla_followup_text"
            render={({ field }) => (
              <FormItem>
                <FormLabel>After-hours SLA promise</FormLabel>
                <FormControl>
                  <Input placeholder="A specialist will reply within one business day." {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        <p className="text-xs text-muted-foreground">
          The relevance-threshold (RAG grounding) field lives in this config too, but it's tuned on
          the Knowledge screen and isn't shown here.
        </p>

        <Button type="submit" disabled={patch.isPending}>
          {patch.isPending ? "Saving…" : "Save configuration"}
        </Button>
      </form>
    </Form>
  );
}

function ConfigStep() {
  const { data, isLoading, isError, refetch } = useSettings();
  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full rounded-lg" />
        <Skeleton className="h-10 w-full rounded-lg" />
        <Skeleton className="h-40 w-full rounded-lg" />
      </div>
    );
  }
  if (isError || !data) {
    return <ErrorState message="Couldn't load your agent settings." onRetry={() => void refetch()} />;
  }
  return <ConfigForm config={data.config} />;
}

// ── step 6: allowed domains ──────────────────────────────────────────────────────────────────

const domainSchema = z.object({
  domain: z
    .string()
    .min(1, "Enter a domain")
    .regex(/^[a-z0-9.-]+\.[a-z]{2,}$/i, "Enter a bare host, e.g. shop.example.com"),
});

function DomainsStep() {
  const qc = useQueryClient();
  const { data: domains, isLoading, isError, refetch } = useDomains();
  const form = useForm<{ domain: string }>({
    resolver: zodResolver(domainSchema),
    defaultValues: { domain: "" },
  });

  const invalidate = () => void qc.invalidateQueries({ queryKey: ["admin", "allowed-domains"] });

  const add = useMutation({
    mutationFn: async (domain: string) =>
      unwrap(await api.POST("/api/v1/admin/allowed-domains", { body: { domain } })),
    onSuccess: () => {
      toast.success("Domain added");
      form.reset();
      invalidate();
    },
    onError: (err) => toast.error("Couldn't add domain", { description: errMessage(err, "Try again.") }),
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE("/api/v1/admin/allowed-domains/{domain_id}", {
          params: { path: { domain_id: id } },
        })
      ),
    onSuccess: () => {
      toast.success("Domain removed");
      invalidate();
    },
    onError: (err) => toast.error("Couldn't remove domain", { description: errMessage(err, "Try again.") }),
  });

  return (
    <div className="space-y-6">
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((v) => add.mutate(v.domain.trim().toLowerCase()))}
          className="flex flex-col gap-3 rounded-xl border bg-muted/30 p-4 sm:flex-row sm:items-start"
        >
          <FormField
            control={form.control}
            name="domain"
            render={({ field }) => (
              <FormItem className="flex-1">
                <FormLabel className="sr-only">Domain</FormLabel>
                <FormControl>
                  <Input placeholder="shop.example.com" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={add.isPending} className="sm:mt-0">
            <Plus className="size-4" />
            {add.isPending ? "Adding…" : "Add domain"}
          </Button>
        </form>
      </Form>

      {isLoading ? (
        <Skeleton className="h-14 w-full rounded-lg" />
      ) : isError ? (
        <ErrorState message="Couldn't load your allowed domains." onRetry={() => void refetch()} />
      ) : !domains?.length ? (
        <EmptyState
          icon={Globe}
          title="No domains allowed yet"
          description="Add the sites permitted to embed your widget. The widget won't load elsewhere."
        />
      ) : (
        <ul className="divide-y rounded-xl border bg-card">
          {domains.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="flex items-center gap-2.5">
                <Globe className="size-4 text-muted-foreground" />
                <span className="text-sm font-medium">{d.domain}</span>
              </div>
              <ConfirmDialog
                trigger={
                  <Button variant="ghost" size="icon-sm" aria-label={`Remove ${d.domain}`}>
                    <Trash2 className="size-4" />
                  </Button>
                }
                title="Remove allowed domain?"
                description={`The widget will stop loading on ${d.domain}.`}
                confirmText="Remove"
                destructive
                onConfirm={() => remove.mutate(d.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── step 7: invite staff ─────────────────────────────────────────────────────────────────────

const inviteSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  role: z.string().min(1),
});

type InviteValues = z.infer<typeof inviteSchema>;

function staffStatus(s: Staff): string {
  if (!s.is_active) return "suspended";
  return s.email_verified ? "active" : "pending";
}

function StaffStep() {
  const qc = useQueryClient();
  const { data: staff, isLoading, isError, refetch } = useStaff();
  const form = useForm<InviteValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: "agent" },
  });

  const invite = useMutation({
    mutationFn: async (values: InviteValues) =>
      unwrap(await api.POST("/api/v1/admin/staff", { body: values })),
    onSuccess: () => {
      toast.success("Invitation sent");
      form.reset({ email: "", role: "agent" });
      void qc.invalidateQueries({ queryKey: ["admin", "staff"] });
    },
    onError: (err) => toast.error("Couldn't invite", { description: errMessage(err, "Try again.") }),
  });

  return (
    <div className="space-y-6">
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((v) => invite.mutate(v))}
          className="grid gap-3 rounded-xl border bg-muted/30 p-4 sm:grid-cols-[1fr_auto_auto] sm:items-start"
        >
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="sr-only">Email</FormLabel>
                <FormControl>
                  <Input type="email" placeholder="teammate@company.com" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="role"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="sr-only">Role</FormLabel>
                <Select onValueChange={field.onChange} value={field.value}>
                  <FormControl>
                    <SelectTrigger className="w-full sm:w-36">
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {STAFF_ROLES.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        {r.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" disabled={invite.isPending}>
            <UserPlus className="size-4" />
            {invite.isPending ? "Inviting…" : "Invite"}
          </Button>
        </form>
      </Form>

      {isLoading ? (
        <Skeleton className="h-14 w-full rounded-lg" />
      ) : isError ? (
        <ErrorState message="Couldn't load your team." onRetry={() => void refetch()} />
      ) : !staff?.length ? (
        <EmptyState icon={Users} title="No teammates yet" description="Invite your first agent or admin above." />
      ) : (
        <ul className="divide-y rounded-xl border bg-card">
          {staff.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{s.email}</p>
                <p className="text-xs capitalize text-muted-foreground">{s.role}</p>
              </div>
              <StatusBadge value={staffStatus(s)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── step 8: embed ────────────────────────────────────────────────────────────────────────────

const CSP_RULES = `script-src <widget-origin>;
connect-src <api-origin>;
img-src data:;`;

function EmbedStep() {
  const { data: snippet, isLoading, isError, refetch } = useEmbed();

  const copy = (text: string, label: string) => {
    void navigator.clipboard
      .writeText(text)
      .then(() => toast.success(`${label} copied`))
      .catch(() => toast.error("Couldn't copy to clipboard"));
  };

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-32 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
    );
  }
  if (isError || !snippet) {
    return <ErrorState message="Couldn't load your embed snippet." onRetry={() => void refetch()} />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">
            Paste this just before the closing <code className="rounded bg-muted px-1 py-0.5 text-xs">&lt;/body&gt;</code> tag.
          </p>
          <Button variant="outline" size="sm" onClick={() => copy(snippet.snippet, "Snippet")}>
            <Copy className="size-4" />
            Copy
          </Button>
        </div>
        <div className="overflow-x-auto rounded-xl border bg-muted/50">
          <pre className="p-4 text-xs leading-relaxed">
            <code>{snippet.snippet}</code>
          </pre>
        </div>
        <p className="text-xs text-muted-foreground">
          Widget key <span className="font-mono tabular-nums">{snippet.widget_key}</span>
        </p>
      </div>

      <div className="space-y-3 rounded-xl border p-4">
        <div className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-muted-foreground" />
          <h3 className="text-sm font-medium">Content-Security-Policy</h3>
        </div>
        <p className="text-sm text-muted-foreground">
          If your site enforces a strict CSP, allow the widget with these directives:
        </p>
        <div className="overflow-x-auto rounded-lg border bg-muted/40">
          <pre className="p-4 text-xs leading-relaxed">
            <code>{CSP_RULES}</code>
          </pre>
        </div>
        <Button variant="ghost" size="sm" onClick={() => copy(CSP_RULES, "CSP rules")}>
          <Copy className="size-4" />
          Copy CSP rules
        </Button>
      </div>
    </div>
  );
}

// ── step rail ────────────────────────────────────────────────────────────────────────────────

function StepRail({
  active,
  done,
  completed,
  onSelect,
}: {
  active: StepKey;
  done: Record<StepKey, boolean>;
  completed: number;
  onSelect: (key: StepKey) => void;
}) {
  const pct = Math.round((completed / STEPS.length) * 100);
  return (
    <Card className="gap-0 py-4 md:sticky md:top-6">
      <div className="space-y-2 px-4 pb-4">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">Setup progress</span>
          <span className="text-muted-foreground tabular-nums">
            {completed} / {STEPS.length}
          </span>
        </div>
        <Progress value={pct} aria-label={`Setup ${pct}% complete`} />
      </div>
      <nav className="flex flex-col gap-0.5 px-2" aria-label="Onboarding steps">
        {STEPS.map((s, i) => {
          const isActive = s.key === active;
          const isDone = done[s.key];
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => onSelect(s.key)}
              aria-current={isActive ? "step" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors",
                isActive ? "bg-accent text-accent-foreground" : "hover:bg-muted/60"
              )}
            >
              <span
                className={cn(
                  "grid size-7 shrink-0 place-items-center rounded-full border text-xs font-semibold tabular-nums",
                  isDone
                    ? "border-transparent bg-success/15 text-success"
                    : isActive
                      ? "border-primary text-primary"
                      : "border-border text-muted-foreground"
                )}
              >
                {isDone ? <Check className="size-3.5" /> : i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{s.label}</span>
                <span className="block truncate text-xs text-muted-foreground">{s.hint}</span>
              </span>
            </button>
          );
        })}
      </nav>
    </Card>
  );
}

// ── page ─────────────────────────────────────────────────────────────────────────────────────

export function OnboardingPage() {
  const [active, setActive] = useState<StepKey>("industry");
  const resumed = useRef(false);

  const tenantQ = useTenant();
  const settingsQ = useSettings();
  const sourcesQ = useSources();
  const datasetsQ = useDatasets();
  const domainsQ = useDomains();
  const staffQ = useStaff();
  const embedQ = useEmbed();

  const tenant = tenantQ.data;
  const cfg = settingsQ.data?.config ?? {};

  const done: Record<StepKey, boolean> = {
    industry: !!tenant?.industry,
    templates: (datasetsQ.data?.length ?? 0) > 0,
    knowledge: (sourcesQ.data?.length ?? 0) > 0,
    records: (datasetsQ.data?.length ?? 0) > 0,
    config: !!(asStr(cfg.welcome_message) || asStr(cfg.persona)),
    domains: (domainsQ.data?.length ?? 0) > 0,
    staff: (staffQ.data?.length ?? 0) > 1,
    embed: !!embedQ.data?.snippet,
  };
  const completed = STEPS.filter((s) => done[s.key]).length;

  // Resume: once the derived state has loaded for the first time, jump to the first incomplete
  // step so returning users land where they left off.
  const settled =
    !tenantQ.isLoading &&
    !settingsQ.isLoading &&
    !sourcesQ.isLoading &&
    !datasetsQ.isLoading &&
    !domainsQ.isLoading &&
    !staffQ.isLoading &&
    !embedQ.isLoading;

  useEffect(() => {
    if (resumed.current || !settled || !tenant) return;
    resumed.current = true;
    const first = STEPS.find((s) => !done[s.key]);
    setActive(first ? first.key : "embed");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled, tenant]);

  if (tenantQ.isLoading) {
    return (
      <div>
        <PageHeader title="Set up your workspace" description="Getting your setup ready…" />
        <div className="grid gap-6 md:grid-cols-[280px_minmax(0,1fr)]">
          <Skeleton className="h-80 w-full rounded-xl" />
          <Skeleton className="h-96 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  if (tenantQ.isError || !tenant) {
    return (
      <div>
        <PageHeader title="Set up your workspace" />
        <ErrorState
          title="Couldn't load your workspace"
          message="We couldn't reach your workspace. Check your connection and try again."
          onRetry={() => void tenantQ.refetch()}
        />
      </div>
    );
  }

  const current = STEPS.find((s) => s.key === active) ?? STEPS[0];
  const currentIndex = STEPS.findIndex((s) => s.key === active);
  const StepIcon = current.icon;

  const goPrev = () => {
    if (currentIndex > 0) setActive(STEPS[currentIndex - 1].key);
  };
  const goNext = () => {
    if (currentIndex < STEPS.length - 1) setActive(STEPS[currentIndex + 1].key);
  };

  const renderStep = () => {
    switch (active) {
      case "industry":
        return <IndustryStep tenant={tenant} />;
      case "templates":
        return <TemplatesStep industry={tenant.industry} />;
      case "knowledge":
        return <KnowledgeStep />;
      case "records":
        return <RecordsStep industry={tenant.industry} />;
      case "config":
        return <ConfigStep />;
      case "domains":
        return <DomainsStep />;
      case "staff":
        return <StaffStep />;
      case "embed":
        return <EmbedStep />;
    }
  };

  return (
    <div>
      <PageHeader
        title={`Set up ${tenant.name}`}
        description="Walk through each step to get your AI support agent live. Your progress is saved automatically."
        actions={
          <span className="inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs font-medium">
            <span className="text-muted-foreground">Step</span>
            <span className="tabular-nums">
              {currentIndex + 1} of {STEPS.length}
            </span>
          </span>
        }
      />

      <div className="grid gap-6 md:grid-cols-[280px_minmax(0,1fr)] md:items-start">
        <StepRail active={active} done={done} completed={completed} onSelect={setActive} />

        <Card>
          <CardHeader className="border-b">
            <div className="flex items-start gap-3">
              <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
                <StepIcon className="size-5" />
              </div>
              <div className="space-y-1">
                <CardTitle className="flex items-center gap-2">
                  {current.label}
                  {done[current.key] && <StatusBadge value="ready" />}
                </CardTitle>
                <CardDescription>{current.description}</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>{renderStep()}</CardContent>
          <CardFooter className="justify-between border-t">
            <Button variant="ghost" onClick={goPrev} disabled={currentIndex === 0}>
              <ArrowLeft className="size-4" />
              Back
            </Button>
            <Button
              variant="outline"
              onClick={goNext}
              disabled={currentIndex === STEPS.length - 1}
            >
              Next
              <ArrowRight className="size-4" />
            </Button>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}

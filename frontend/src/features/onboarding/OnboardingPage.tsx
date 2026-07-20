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
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  Copy,
  Download,
  FileText,
  Globe,
  MessageSquare,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
  Users,
  Zap,
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
import { getAccessToken, type Industry } from "@/lib/auth";
import { usePageBanner } from "@/lib/pageBanner";
import { cn } from "@/lib/utils";
import type { components } from "@/api/generated/schema";
import {
  type Tenant,
  useDatasets,
  useDomains,
  useEmbed,
  useSettings,
  useSources,
  useStaff,
} from "./queries";
import { RECORD_TYPES_BY_INDUSTRY } from "./recordTypes";
import { STEPS } from "./steps";
import { useOnboardingStore } from "./store";
import { useOnboardingProgress } from "./useOnboardingProgress";
import { useOnboardingStatus } from "./useOnboardingStatus";

type SourceOut = components["schemas"]["SourceOut"];
type UploadReport = components["schemas"]["DatasetUploadReport"];
type Staff = components["schemas"]["StaffResponse"];

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
  const qc = useQueryClient();
  const [choice, setChoice] = useState<Industry>("retail");

  const setIndustry = useMutation({
    mutationFn: async (industry: Industry) =>
      unwrap(await api.PATCH("/api/v1/admin/tenant/industry", { body: { industry } })),
    onSuccess: () => {
      toast.success("Industry set");
      void qc.invalidateQueries({ queryKey: ["tenant"] });
    },
    onError: (err) => toast.error("Couldn't set industry", { description: errMessage(err, "Try again.") }),
  });

  // Chosen once, here, instead of at signup — immutable afterward (no endpoint to change it).
  if (!tenant.industry) {
    return (
      <div className="space-y-5">
        <p className="text-sm text-muted-foreground">
          Your industry determines the record types your AI agent can work with. Once selected,
          it can&apos;t be changed.
        </p>
        <div className="grid gap-2 sm:max-w-xs">
          <Label htmlFor="industry-choice">Industry</Label>
          <Select value={choice} onValueChange={(v) => setChoice(v as Industry)}>
            <SelectTrigger id="industry-choice" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(INDUSTRY_LABELS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button onClick={() => setIndustry.mutate(choice)} disabled={setIndustry.isPending}>
          {setIndustry.isPending ? "Saving…" : "Confirm industry"}
        </Button>
      </div>
    );
  }

  const label = INDUSTRY_LABELS[tenant.industry] ?? tenant.industry;
  const recordTypes = RECORD_TYPES_BY_INDUSTRY[tenant.industry] ?? [];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-gradient-to-br from-secondary/50 to-secondary/10 px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
            <Building2 className="size-5" />
          </div>
          <div>
            <p className="text-sm font-medium">{label}</p>
            <p className="text-xs text-muted-foreground">{tenant.name}</p>
          </div>
        </div>
        <StatusBadge value="ready" />
      </div>
      <p className="text-xs font-medium text-muted-foreground">Supported record types</p>
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

function TemplatesStep({
  industry,
  onConfirm,
}: {
  industry: string;
  onConfirm?: () => void;
}) {
  const recordTypes = RECORD_TYPES_BY_INDUSTRY[industry] ?? [];
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Download a template for each record type, fill it with your customer data, then upload it
        in the <span className="font-semibold text-foreground">Customer Records</span> step.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {recordTypes.map((rt) => (
          <div
            key={rt}
            className="flex items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3"
          >
            <div className="flex items-center gap-3">
              <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-ai-accent/12 text-ai-accent">
                <FileText className="size-4" />
              </div>
              <div>
                <p className="text-sm font-medium capitalize">{rt}</p>
                <p className="text-[10px] text-muted-foreground">CSV</p>
              </div>
            </div>
            <Button
              variant="outline"
              size="icon-sm"
              className="rounded-full"
              aria-label={`Download ${rt} template`}
              title={`Download ${rt} template`}
              onClick={() => {
                void downloadTemplate(rt);
                onConfirm?.();
              }}
            >
              <Download className="size-4" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── step 3: knowledge ────────────────────────────────────────────────────────────────────────

type KnowledgeKind = "file" | "url" | "paste";

const KNOWLEDGE_KINDS = [
  { value: "file", label: "File upload" },
  { value: "url", label: "URL" },
  { value: "paste", label: "Paste Text" },
] as const;

function KnowledgeStep() {
  const qc = useQueryClient();
  const { data: sources, isLoading, isError, refetch } = useSources();
  const [kind, setKind] = useState<KnowledgeKind>("file");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [content, setContent] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-4 rounded-xl border bg-gradient-to-br from-secondary/40 to-secondary/10 p-4 lg:min-h-[14rem]">
        <div className="grid gap-2">
          <Label>Source type</Label>
          <div className="flex flex-wrap gap-2">
            {KNOWLEDGE_KINDS.map((k) => (
              <Button
                key={k.value}
                type="button"
                variant="outline"
                size="sm"
                className={cn(
                  "rounded-full text-xs",
                  // Mirrors the left panel's active-step treatment: a plain fill + bold text,
                  // no border accent — not a bordered "selected" chip.
                  kind === k.value
                    ? "border-transparent bg-primary/10 font-medium text-primary"
                    : // A literal neutral grey, not --muted (a pale BLUE tint in this design
                      // system) — "grayed out" needs an actual grey, not another brand blue.
                      "border-gray-200 bg-gray-100 text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400"
                )}
                onClick={() => setKind(k.value)}
              >
                {k.label}
              </Button>
            ))}
          </div>
        </div>

        {kind === "file" && (
          <div className="grid gap-2">
            <Label htmlFor="kb-file">File</Label>
            <Input
              readOnly
              value={file?.name ?? ""}
              placeholder="Click to choose a file"
              className="cursor-pointer text-xs md:text-xs"
              onClick={() => fileInputRef.current?.click()}
            />
            <input
              ref={fileInputRef}
              id="kb-file"
              type="file"
              className="sr-only"
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
              className="text-xs md:text-xs"
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
              placeholder="Paste an FAQ, policy, or any text the agent should know…"
              className="field-sizing-fixed h-9 min-h-9 resize-none overflow-hidden text-xs md:text-xs"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
        )}

        <div className="grid gap-2">
          <Label htmlFor="kb-name">
            Name <span className="font-normal text-muted-foreground">(optional)</span>
          </Label>
          <Input
            id="kb-name"
            placeholder="e.g. Returns policy"
            className="text-xs md:text-xs"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div className="flex justify-end">
          <Button onClick={() => add.mutate()} disabled={add.isPending}>
            {add.isPending ? "Adding…" : "Add source"}
          </Button>
        </div>
      </div>

      <div className="flex flex-col rounded-xl border bg-card lg:min-h-[14rem]">
        <h3 className="px-4 py-3 text-sm font-medium">Existing sources</h3>
        <div className="flex-1 p-3">
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
          <ul className="divide-y">
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
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-4">
        <div className="space-y-4 rounded-xl border bg-gradient-to-br from-secondary/40 to-secondary/10 p-4 lg:min-h-[14rem]">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="rec-type">Record type</Label>
              <Select value={recordType} onValueChange={setRecordType}>
                <SelectTrigger id="rec-type" className="w-full text-xs">
                  <SelectValue placeholder="Select a record type" />
                </SelectTrigger>
                <SelectContent>
                  {recordTypes.map((rt) => (
                    <SelectItem key={rt} value={rt} className="text-xs capitalize">
                      {rt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="rec-file">CSV file</Label>
              <Input
                readOnly
                value={file?.name ?? ""}
                placeholder="Click to choose a file"
                className="cursor-pointer text-xs md:text-xs"
                onClick={() => fileInputRef.current?.click()}
              />
              <input
                ref={fileInputRef}
                id="rec-file"
                type="file"
                className="sr-only"
                accept=".csv"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button onClick={() => upload.mutate()} disabled={upload.isPending}>
              {upload.isPending ? "Uploading…" : "Upload dataset"}
            </Button>
          </div>
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
                <span className="tabular-nums">{report.row_errors.length}</span> row error(s). First:
                row {report.row_errors[0].row}, {report.row_errors[0].error}
              </p>
            ) : null}
          </div>
        )}
      </div>

      <div className="flex flex-col rounded-xl border bg-card lg:min-h-[14rem]">
        <h3 className="px-4 py-3 text-sm font-medium">Uploaded datasets</h3>
        <div className="flex-1 p-3">
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
            <ul className="divide-y">
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

function ConfigForm({ config, onSaved }: { config: Record<string, unknown>; onSaved?: () => void }) {
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
      onSaved?.();
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
                    className="text-xs md:text-xs"
                    {...field}
                  />
                </FormControl>
                <FormDescription className="text-xs">How the agent should sound and behave.</FormDescription>
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
                  <Input placeholder="Hi! How can I help you today?" className="text-xs md:text-xs" {...field} />
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
                    <SelectTrigger className="w-full text-xs sm:max-w-xs">
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {LANGUAGES.map((l) => (
                      <SelectItem key={l.value} value={l.value} className="text-xs">
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

        <div className="space-y-3 rounded-xl border border-accent-slate/30 bg-accent-powder/15 p-4">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-slate/20 text-accent-slate">
              <Zap className="size-4" />
            </span>
            <div>
              <p className="text-sm font-medium">Escalation triggers</p>
              <p className="text-xs text-muted-foreground">
                When any active trigger fires, the conversation hands off to a human.
              </p>
            </div>
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
                  <Input
                    placeholder="lawsuit, chargeback, cancel account"
                    className="text-xs md:text-xs"
                    {...field}
                  />
                </FormControl>
                <FormDescription className="text-xs">
                  Comma-separated. A match forces a human hand-off.
                </FormDescription>
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
                  <Input
                    placeholder="A specialist will reply within one business day."
                    className="text-xs md:text-xs"
                    {...field}
                  />
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

function ConfigStep({ onSaved }: { onSaved?: () => void }) {
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
  return <ConfigForm config={data.config} onSaved={onSaved} />;
}

// ── step 6: allowed domains ──────────────────────────────────────────────────────────────────

const domainSchema = z.object({
  domain: z
    .string()
    .min(1, "Enter a domain")
    .regex(
      /^([a-z0-9.-]+\.[a-z]{2,}|localhost)(:\d+)?$/i,
      "Enter a bare host, e.g. shop.example.com (localhost is fine for local testing)"
    ),
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
    <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((v) => add.mutate(v.domain.trim().toLowerCase()))}
          className="flex flex-col gap-3 rounded-xl border bg-gradient-to-br from-secondary/40 to-secondary/10 p-4 sm:flex-row sm:items-start lg:min-h-[26rem] lg:flex-col lg:items-stretch"
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

      <div className="space-y-3">
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
    <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((v) => invite.mutate(v))}
          className="grid gap-3 rounded-xl border bg-gradient-to-br from-secondary/40 to-secondary/10 p-4 sm:grid-cols-[1fr_auto_auto] sm:items-start"
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
            {invite.isPending ? "Inviting…" : "Invite"}
          </Button>
        </form>
      </Form>

      <div className="space-y-3">
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
              <StatusBadge value={staffStatus(s)} className="w-24 justify-center" />
            </li>
          ))}
        </ul>
      )}
      </div>
    </div>
  );
}

// ── step 8: embed ────────────────────────────────────────────────────────────────────────────

const CSP_RULES = `script-src <widget-origin>;
connect-src <api-origin>;
img-src data:;`;

function EmbedStep({ onConfirm }: { onConfirm?: () => void }) {
  const { data: snippet, isLoading, isError, refetch } = useEmbed();

  const copy = (text: string, label: string, confirms?: boolean) => {
    void navigator.clipboard
      .writeText(text)
      .then(() => {
        toast.success(`${label} copied`);
        if (confirms) onConfirm?.();
      })
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
          <Button variant="outline" size="sm" onClick={() => copy(snippet.snippet, "Snippet", true)}>
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

      <div className="space-y-3 rounded-xl border border-accent-navy/25 bg-accent-powder/15 p-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-navy/12 text-accent-navy">
              <ShieldCheck className="size-4" />
            </span>
            <h3 className="text-sm font-medium">Content-Security-Policy</h3>
          </div>
          <Button variant="ghost" size="sm" onClick={() => copy(CSP_RULES, "CSP rules")}>
            <Copy className="size-4" />
            Copy CSP rules
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          If your site enforces a strict CSP, allow the widget with these directives:
        </p>
        <div className="overflow-x-auto rounded-lg border bg-muted/40">
          <pre className="p-4 text-xs leading-relaxed">
            <code>{CSP_RULES}</code>
          </pre>
        </div>
      </div>
    </div>
  );
}

// ── page ─────────────────────────────────────────────────────────────────────────────────────

export function OnboardingPage() {
  // Navigation state (active step, config/embed confirmation) lives in a shared store, not local
  // state — `app-sidebar.tsx` needs to read and drive the exact same state, since it now renders
  // this step list itself (replacing the normal console nav) while setup is incomplete.
  const active = useOnboardingStore((s) => s.active);
  const setActive = useOnboardingStore((s) => s.setActive);
  const confirmStep = useOnboardingStore((s) => s.confirmStep);
  const resumed = useRef(false);
  const navigate = useNavigate();

  const { tenant, tenantQ, done, settled } = useOnboardingProgress();
  // Whether this is a first-time run-through vs. an admin revisiting via the "Setup guide" nav
  // item after already finishing once — the welcome banner below only makes sense for the former.
  const { data: onboardingStatus } = useOnboardingStatus();
  const isRevisit = onboardingStatus?.completed === true;

  // Resume: once the derived state has loaded for the first time, jump to the first incomplete
  // step so returning users land where they left off.
  useEffect(() => {
    if (resumed.current || !settled || !tenant) return;
    resumed.current = true;
    // `done.industry` is derived from the tenant having an industry — true for every account
    // from the moment it's created, so it's never a real signal of progress. Without this guard,
    // "first incomplete step" always skips straight past it to "templates", and a first-time
    // visitor never sees step 1 at all. Land on industry until the account has SOME real
    // progress elsewhere; once it does, resume normally.
    const hasRealProgress = STEPS.slice(1).some((s) => done[s.key]);
    const first = hasRealProgress ? STEPS.find((s) => !done[s.key]) : STEPS[0];
    setActive(first ? first.key : "embed");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled, tenant]);

  // Hands the top bar a title/subtitle for the whole wizard (not per-step — the step itself is
  // already shown in the card below) so the app bar reads as part of onboarding. The first-time
  // copy only makes sense for an actual first run-through — an admin revisiting via "Setup guide"
  // after already finishing once gets a plainer banner instead ("complete each step to launch"
  // reads oddly once the agent is already live). Cleared on unmount either way.
  useEffect(() => {
    usePageBanner.getState().set(
      isRevisit
        ? {
            title: "Setup guide",
            subtitle: "Review any part of your AI agent's setup.",
          }
        : {
            title: "Welcome! Let's set up your AI agent.",
            subtitle:
              "Complete each step to launch your AI support agent. Your progress is saved automatically.",
          }
    );
    return () => usePageBanner.getState().clear();
  }, [isRevisit]);

  if (tenantQ.isLoading) {
    return (
      <div>
        <PageHeader title="Set up your account" description="Getting your setup ready…" />
        <div className="space-y-6">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-96 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  if (tenantQ.isError || !tenant) {
    return (
      <div>
        <PageHeader title="Set up your account" />
        <ErrorState
          title="Couldn't load your account"
          message="We couldn't reach your account. Check your connection and try again."
          onRetry={() => void tenantQ.refetch()}
        />
      </div>
    );
  }

  const current = STEPS.find((s) => s.key === active) ?? STEPS[0];
  const currentIndex = STEPS.findIndex((s) => s.key === active);
  const StepIcon = current.icon;

  const isLastStep = currentIndex === STEPS.length - 1;

  // Optional steps (allowed domains, invite team — flagged in steps.ts) don't gate "Next": the
  // user can move on without completing them. Each step's own `done` signal still tracks real
  // state, so the sidebar checkmarks stay honest.
  const canAdvance = done[current.key] || !!current.optional;

  const goNext = () => {
    if (isLastStep) {
      toast.success("Your AI agent is set up!", {
        description: "It's live and ready to help your customers.",
      });
      navigate("/overview");
      return;
    }
    setActive(STEPS[currentIndex + 1].key);
  };

  const renderStep = () => {
    switch (active) {
      case "industry":
        return <IndustryStep tenant={tenant} />;
      case "templates":
        return <TemplatesStep industry={tenant.industry ?? ""} onConfirm={() => confirmStep("templates")} />;
      case "knowledge":
        return <KnowledgeStep />;
      case "records":
        return <RecordsStep industry={tenant.industry ?? ""} />;
      case "config":
        return <ConfigStep onSaved={() => confirmStep("config")} />;
      case "domains":
        return <DomainsStep />;
      case "staff":
        return <StaffStep />;
      case "embed":
        return <EmbedStep onConfirm={() => confirmStep("embed")} />;
    }
  };

  return (
    // `overflow-hidden gap-0 py-0`: the default Card reserves its own py-6/gap-6 padding around
    // sections regardless of their background, which left a strip of the card's own white
    // background above CardHeader — looked like a stray white patch above the step icon no
    // matter what color the header itself was. Overriding both, and giving each section its own
    // explicit padding, makes the header's background actually reach the card's rounded top edge.
    <Card className="gap-0 overflow-hidden py-0 shadow-sm">
      <CardHeader className="gap-2 border-b bg-gradient-to-br from-secondary/70 to-secondary/25 px-6 py-5">
        <div className="flex items-start gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
            <StepIcon className="size-5" />
          </div>
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-lg">{current.label}</CardTitle>
            <CardDescription className="text-xs">{current.description}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="min-h-[14rem] px-6 py-5">{renderStep()}</CardContent>
      {/* Only during the actual first-time run-through — once onboarding is already complete,
          revisiting via "Setup guide" is a pure review: no "Finish" action to race back through,
          and nothing here should look like it's still gating progress to the dashboard. */}
      {!isRevisit && (
        <CardFooter className="justify-end border-t px-6 py-5">
          {/* No "Back" — the step list in the sidebar already jumps to any past/current step.
              Locked until the current step reports done, so setup can't be raced past a step
              that hasn't actually been completed yet. On the last step this becomes "Finish",
              confirming the agent is set up and returning to the dashboard. */}
          <Button
            size="icon"
            className="rounded-full bg-gradient-to-br from-primary to-primary/70 shadow-sm transition-shadow hover:shadow-md"
            aria-label={isLastStep ? "Finish setup" : "Next step"}
            title={isLastStep ? "Finish setup" : "Next step"}
            onClick={goNext}
            disabled={!canAdvance}
          >
            {isLastStep ? <CheckCircle2 className="size-4" /> : <ArrowRight className="size-4" />}
          </Button>
        </CardFooter>
      )}
    </Card>
  );
}

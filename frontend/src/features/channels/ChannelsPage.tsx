/** FE-Channels — widget embed, key rotation, and allowed-domain management. Mounted at
 * `/admin/channels`. All calls go through the admin channel endpoints:
 *   GET  /admin/embed-snippet        → { widget_key, snippet }
 *   POST /admin/widget-key/rotate    → { widget_key }
 *   GET  /admin/allowed-domains      → [{ id, domain }]
 *   POST /admin/allowed-domains      → { id, domain }
 *   DELETE /admin/allowed-domains/{id}
 */

import { useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Check,
  Code2,
  Copy,
  Eye,
  EyeOff,
  Globe,
  KeyRound,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";

import { DataTable } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, unwrap } from "@/lib/api";
import { usePageBanner } from "@/lib/pageBanner";
import type { components } from "@/api/generated/schema";

type EmbedSnippet = components["schemas"]["EmbedSnippetResponse"];
type WidgetKey = components["schemas"]["WidgetKeyResponse"];
type AllowedDomain = components["schemas"]["AllowedDomainResponse"];

// The embed snippet response carries both the snippet markup and the widget key, so the snippet
// card and the key card share one query (TanStack dedupes the identical key into a single fetch).
const EMBED_QUERY_KEY = ["admin", "embed-snippet"] as const;
const DOMAINS_QUERY_KEY = ["admin", "allowed-domains"] as const;

export function ChannelsPage() {
  useEffect(() => {
    usePageBanner.getState().set({
      title: "Channels & embed",
      subtitle:
        "Drop the assistant onto your site, manage the widget key, and control which domains are allowed to load it.",
    });
    return () => usePageBanner.getState().clear();
  }, []);

  return (
    <div className="space-y-6">
      <EmbedSnippetCard />
      <WidgetKeyCard />
      <AllowedDomainsCard />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Copy-to-clipboard button                                                    */
/* -------------------------------------------------------------------------- */

interface CopyButtonProps {
  value: string;
  label?: string;
  size?: "sm" | "icon-sm";
  disabled?: boolean;
}

function CopyButton({ value, label = "Copy", size = "sm", disabled }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const iconOnly = size === "icon-sm";

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success("Copied to clipboard");
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Couldn't copy to clipboard");
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      size={size}
      disabled={disabled}
      onClick={handleCopy}
      aria-label={iconOnly ? label : undefined}
    >
      {copied ? <Check /> : <Copy />}
      {iconOnly ? null : copied ? "Copied" : label}
    </Button>
  );
}

/* -------------------------------------------------------------------------- */
/* 1. Embed snippet                                                            */
/* -------------------------------------------------------------------------- */

function EmbedSnippetCard() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: EMBED_QUERY_KEY,
    queryFn: async () => unwrap<EmbedSnippet>(await api.GET("/api/v1/admin/embed-snippet")),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Code2 className="size-4 text-muted-foreground" />
          Embed snippet
        </CardTitle>
        <CardDescription>
          Paste this just before the closing <code className="font-mono">&lt;/body&gt;</code> tag on
          every page where the assistant should appear.
        </CardDescription>
        {data ? (
          <CardAction>
            <CopyButton value={data.snippet} label="Copy snippet" />
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {isError ? (
          <ErrorState
            title="Couldn't load the embed snippet"
            message="We couldn't fetch your install code. Check your connection and try again."
            onRetry={() => void refetch()}
          />
        ) : isLoading ? (
          <div className="space-y-2 rounded-lg border bg-muted/40 p-4">
            <Skeleton className="h-3.5 w-4/5" />
            <Skeleton className="h-3.5 w-3/5" />
            <Skeleton className="h-3.5 w-2/3" />
          </div>
        ) : (
          <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-4 text-xs leading-relaxed">
            <code className="font-mono text-foreground">{data?.snippet}</code>
          </pre>
        )}

        <CspNote />
      </CardContent>
    </Card>
  );
}

/** Reminder of the CSP directives a host site needs so the widget can load and reach the API. */
function CspNote() {
  return (
    <div className="rounded-lg border bg-muted/40 p-4 text-xs text-muted-foreground">
      <p className="font-medium text-foreground">Content Security Policy</p>
      <p className="mt-1">If your site sends a CSP header, allow the widget with these directives:</p>
      <ul className="mt-3 space-y-1.5">
        <li className="flex flex-wrap items-center gap-2">
          <CspToken>script-src</CspToken>
          <span>the widget origin</span>
        </li>
        <li className="flex flex-wrap items-center gap-2">
          <CspToken>connect-src</CspToken>
          <span>the API origin</span>
        </li>
        <li className="flex flex-wrap items-center gap-2">
          <CspToken>img-src</CspToken>
          <span>
            <code className="font-mono text-foreground">data:</code>
          </span>
        </li>
      </ul>
    </div>
  );
}

function CspToken({ children }: { children: string }) {
  return (
    <code className="rounded bg-background px-1.5 py-0.5 font-mono text-foreground">{children}</code>
  );
}

/* -------------------------------------------------------------------------- */
/* 2. Widget key                                                               */
/* -------------------------------------------------------------------------- */

function maskKey(key: string): string {
  if (!key) return "";
  if (key.length <= 10) return "•".repeat(10);
  return `${key.slice(0, 4)}${"•".repeat(12)}${key.slice(-4)}`;
}

function WidgetKeyCard() {
  const queryClient = useQueryClient();
  const [revealed, setRevealed] = useState(false);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: EMBED_QUERY_KEY,
    queryFn: async () => unwrap<EmbedSnippet>(await api.GET("/api/v1/admin/embed-snippet")),
  });

  const rotate = useMutation({
    mutationFn: async () =>
      unwrap<WidgetKey>(await api.POST("/api/v1/admin/widget-key/rotate")),
    onSuccess: () => {
      toast.success("Widget key rotated. Update your embed snippet to keep the widget working.");
      setRevealed(false);
      void queryClient.invalidateQueries({ queryKey: EMBED_QUERY_KEY });
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Couldn't rotate the widget key");
    },
  });

  const key = data?.widget_key ?? "";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="size-4 text-muted-foreground" />
          Widget key
        </CardTitle>
        <CardDescription>
          Public identifier that ties the widget to your account. It's safe to expose in
          client-side code, but rotate it if you suspect it has been misused.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isError ? (
          <ErrorState
            title="Couldn't load the widget key"
            message="We couldn't fetch your widget key. Check your connection and try again."
            onRetry={() => void refetch()}
          />
        ) : isLoading ? (
          <Skeleton className="h-11 w-full max-w-md" />
        ) : (
          <div className="flex flex-col gap-3 rounded-lg border bg-muted/40 p-3 sm:flex-row sm:items-center sm:justify-between">
            <code className="min-w-0 flex-1 truncate font-mono text-sm tabular-nums text-foreground">
              {revealed ? key : maskKey(key)}
            </code>
            <div className="flex shrink-0 items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setRevealed((v) => !v)}
                    aria-label={revealed ? "Hide widget key" : "Show widget key"}
                  >
                    {revealed ? <EyeOff /> : <Eye />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{revealed ? "Hide key" : "Reveal key"}</TooltipContent>
              </Tooltip>
              <CopyButton value={key} label="Copy key" size="icon-sm" />
            </div>
          </div>
        )}
      </CardContent>
      <CardFooter className="border-t">
        <ConfirmDialog
          trigger={
            <Button variant="outline" disabled={isLoading || isError || rotate.isPending}>
              <RotateCcw />
              {rotate.isPending ? "Rotating…" : "Rotate key"}
            </Button>
          }
          title="Rotate the widget key?"
          description="The current key stops working immediately. Any embed still using the old key will break until you paste the new snippet on your site."
          confirmText="Rotate key"
          destructive
          onConfirm={() => rotate.mutate()}
        />
      </CardFooter>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* 3. Allowed domains                                                          */
/* -------------------------------------------------------------------------- */

const addDomainSchema = z.object({
  domain: z
    .string()
    .trim()
    .min(1, "Enter a domain")
    .regex(
      /^((\*\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}|localhost)(:\d+)?$/i,
      "Enter a bare domain like app.example.com (no https:// or path) — localhost is fine for local testing"
    ),
});

type AddDomainValues = z.infer<typeof addDomainSchema>;

function AllowedDomainsCard() {
  const queryClient = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: DOMAINS_QUERY_KEY,
    queryFn: async () =>
      unwrap<AllowedDomain[]>(await api.GET("/api/v1/admin/allowed-domains")),
  });

  const form = useForm<AddDomainValues>({
    resolver: zodResolver(addDomainSchema),
    defaultValues: { domain: "" },
  });

  const addDomain = useMutation({
    mutationFn: async (values: AddDomainValues) =>
      unwrap<AllowedDomain>(
        await api.POST("/api/v1/admin/allowed-domains", { body: { domain: values.domain } })
      ),
    onSuccess: (created) => {
      toast.success(`${created.domain} added to allowed domains`);
      void queryClient.invalidateQueries({ queryKey: DOMAINS_QUERY_KEY });
      form.reset();
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Couldn't add that domain");
    },
  });

  const removeDomain = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/v1/admin/allowed-domains/{domain_id}", {
          params: { path: { domain_id: id } },
        })
      );
    },
    onSuccess: () => {
      toast.success("Domain removed");
      void queryClient.invalidateQueries({ queryKey: DOMAINS_QUERY_KEY });
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Couldn't remove that domain");
    },
  });

  const columns = useMemo<ColumnDef<AllowedDomain>[]>(
    () => [
      {
        accessorKey: "domain",
        header: "Domain",
        cell: ({ row }) => (
          <span className="font-mono text-sm text-foreground">{row.original.domain}</span>
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex justify-end">
            <ConfirmDialog
              trigger={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="text-muted-foreground hover:text-destructive"
                  disabled={removeDomain.isPending}
                  aria-label={`Remove ${row.original.domain}`}
                >
                  <Trash2 />
                </Button>
              }
              title="Remove allowed domain?"
              description={`The widget will no longer load on ${row.original.domain}. You can add it back at any time.`}
              confirmText="Remove"
              destructive
              onConfirm={() => removeDomain.mutate(row.original.id)}
            />
          </div>
        ),
      },
    ],
    [removeDomain]
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="size-4 text-muted-foreground" />
          Allowed domains
        </CardTitle>
        <CardDescription>
          The widget only loads on the domains you list here. Add each site's bare hostname.
          Subdomains and wildcards (<code className="font-mono">*.example.com</code>) are supported.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Form {...form}>
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-start"
            onSubmit={form.handleSubmit((values) => addDomain.mutate(values))}
          >
            <FormField
              control={form.control}
              name="domain"
              render={({ field }) => (
                <FormItem className="flex-1">
                  <FormLabel className="sr-only">Domain</FormLabel>
                  <FormControl>
                    <Input placeholder="app.example.com" autoComplete="off" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Button type="submit" disabled={addDomain.isPending}>
              <Plus />
              {addDomain.isPending ? "Adding…" : "Add domain"}
            </Button>
          </form>
        </Form>

        <DataTable
          columns={columns}
          data={data ?? []}
          loading={isLoading}
          error={isError}
          onRetry={() => void refetch()}
          empty={
            <EmptyState
              icon={Globe}
              title="No allowed domains yet"
              description="Add a domain above to let the widget load on your site."
            />
          }
        />
      </CardContent>
    </Card>
  );
}

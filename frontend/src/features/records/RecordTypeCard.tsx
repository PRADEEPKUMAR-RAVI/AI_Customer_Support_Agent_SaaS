/** One card per record type: dataset status + row count, the schema summary, and the CSV/JSON
 * upload flow. Upload posts the file to the backend, which returns the validation report the FE
 * renders verbatim (see ValidationReport). Deletes are gated behind a ConfirmDialog. */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import {
  deleteDataset,
  uploadDataset,
  type DatasetUploadReport,
  type RecordSchemaOut,
} from "./api";
import { ValidationReport } from "./ValidationReport";

function titleCase(v: string): string {
  return v.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function RecordTypeCard({
  schema,
  rowCount,
  updatedAt,
}: {
  schema: RecordSchemaOut;
  rowCount: number | null;
  updatedAt: string | null;
}) {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<DatasetUploadReport | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["records", "datasets"] });
  const label = titleCase(schema.record_type);

  const upload = useMutation({
    mutationFn: () => uploadDataset(schema.record_type, file as File),
    onSuccess: (r) => {
      setReport(r);
      invalidate();
      if (r.ok) {
        setFile(null);
        if (inputRef.current) inputRef.current.value = "";
        toast.success(`Imported ${(r.inserted ?? 0).toLocaleString()} rows into ${label}.`);
      } else {
        toast.error("Upload rejected. See the validation report.");
      }
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const remove = useMutation({
    mutationFn: () => deleteDataset(schema.record_type),
    onSuccess: () => {
      setReport(null);
      invalidate();
      toast.success(`Deleted the ${label} dataset.`);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const hasData = rowCount !== null;
  const aliasKeys = schema.alias_keys ?? [];
  const verifyFields = schema.verify_fields ?? [];
  const returnedFields = schema.returned_fields ?? [];

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <CardHeader className="gap-2 border-b py-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <CardTitle className="truncate text-base">{label}</CardTitle>
            <CardDescription className="truncate font-mono text-xs">
              key {schema.key}
              {aliasKeys.length > 0 ? ` · alias ${aliasKeys.join(", ")}` : ""}
            </CardDescription>
          </div>
          <StatusBadge value={hasData ? "ready" : "no_data"} />
        </div>
      </CardHeader>

      <CardContent className="space-y-4 py-5">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold tabular-nums">
            {hasData ? rowCount!.toLocaleString() : "—"}
          </span>
          <span className="text-sm text-muted-foreground">
            {hasData ? "rows uploaded" : "no dataset uploaded"}
          </span>
        </div>

        {updatedAt ? (
          <p className="text-xs text-muted-foreground">Updated {new Date(updatedAt).toLocaleString()}</p>
        ) : null}

        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">
            Verify: {verifyFields.length > 0 ? verifyFields.join(" or ") : "none"}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {returnedFields.length > 0 ? (
              returnedFields.map((f) => (
                <Badge key={f} variant="secondary" className="font-mono font-normal">
                  {f}
                </Badge>
              ))
            ) : (
              <span className="text-xs text-muted-foreground">No returned fields.</span>
            )}
          </div>
        </div>

        {report ? <ValidationReport report={report} /> : null}
      </CardContent>

      <CardFooter className="flex-wrap gap-2 border-t py-4">
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.json,text/csv,application/json"
          aria-label={`Choose a CSV or JSON file for ${label}`}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className={cn(
            "min-w-0 flex-1 text-sm text-muted-foreground",
            "file:mr-3 file:cursor-pointer file:rounded-md file:border file:border-input file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-secondary-foreground hover:file:bg-secondary/80"
          )}
        />
        <Button size="sm" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>
          <Upload className="size-4" />
          {upload.isPending ? "Uploading…" : "Upload"}
        </Button>
        {hasData ? (
          <ConfirmDialog
            trigger={
              <Button size="sm" variant="outline" disabled={remove.isPending}>
                <Trash2 className="size-4" />
                Delete
              </Button>
            }
            title={`Delete the ${label} dataset?`}
            description="This removes every uploaded row for this record type. Your AI will stop being able to verify or answer questions about it until you upload again."
            confirmText="Delete dataset"
            destructive
            onConfirm={() => remove.mutate()}
          />
        ) : null}
      </CardFooter>
    </Card>
  );
}

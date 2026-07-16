/** Renders the backend's synchronous dataset-validation report verbatim. The backend is the single
 * source of validation truth ([DatasetUploadReport]) — the FE never re-derives ok/errors, it only
 * presents them: a success summary, or the missing headers / duplicate keys / per-row errors that
 * caused a full rejection (nothing is saved unless `ok`). */

import { Badge } from "@/components/ui/badge";
import { ReportBanner } from "@/components/report-banner";

import type { DatasetUploadReport } from "./api";

const MAX_DUPES = 12;
const MAX_ROW_ERRORS = 10;

export function ValidationReport({ report }: { report: DatasetUploadReport }) {
  if (report.ok) {
    return (
      <ReportBanner
        ok
        heading={
          <>
            Imported <span className="tabular-nums">{(report.inserted ?? 0).toLocaleString()}</span>{" "}
            rows.
          </>
        }
      >
        {report.truncated > 0 ? (
          <p className="pl-6 text-muted-foreground">
            <span className="tabular-nums">{report.truncated.toLocaleString()}</span> extra rows
            were truncated to stay within the dataset limit.
          </p>
        ) : null}
      </ReportBanner>
    );
  }

  const missing = report.missing_headers ?? [];
  const dups = report.duplicate_keys ?? [];
  const rowErrors = report.row_errors ?? [];
  const shownErrors = rowErrors.slice(0, MAX_ROW_ERRORS);
  const extraErrors = rowErrors.length - shownErrors.length;
  const extraDupes = dups.length - MAX_DUPES;

  return (
    <ReportBanner ok={false} heading="Upload rejected. Nothing was saved.">
      {missing.length > 0 ? (
        <div className="space-y-1.5 pl-6">
          <p className="text-xs font-medium text-muted-foreground">Missing required headers</p>
          <div className="flex flex-wrap gap-1.5">
            {missing.map((h) => (
              <Badge key={h} variant="outline" className="font-mono font-normal">
                {h}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      {dups.length > 0 ? (
        <div className="space-y-1.5 pl-6">
          <p className="text-xs font-medium text-muted-foreground">Duplicate keys</p>
          <div className="flex flex-wrap gap-1.5">
            {dups.slice(0, MAX_DUPES).map((k) => (
              <Badge key={k} variant="outline" className="font-mono font-normal">
                {k}
              </Badge>
            ))}
            {extraDupes > 0 ? (
              <Badge variant="secondary" className="tabular-nums">
                +{extraDupes} more
              </Badge>
            ) : null}
          </div>
        </div>
      ) : null}

      {rowErrors.length > 0 ? (
        <div className="space-y-1.5 pl-6">
          <p className="text-xs font-medium text-muted-foreground">Row errors</p>
          <ul className="divide-y divide-border overflow-hidden rounded-md border bg-card">
            {shownErrors.map((e) => (
              <li key={e.row} className="flex gap-3 px-3 py-1.5 text-xs">
                <span className="shrink-0 tabular-nums text-muted-foreground">Row {e.row}</span>
                <span className="text-foreground">{e.error}</span>
              </li>
            ))}
          </ul>
          {extraErrors > 0 ? (
            <p className="text-xs text-muted-foreground">
              <span className="tabular-nums">+{extraErrors}</span> more rows with errors.
            </p>
          ) : null}
        </div>
      ) : null}
    </ReportBanner>
  );
}

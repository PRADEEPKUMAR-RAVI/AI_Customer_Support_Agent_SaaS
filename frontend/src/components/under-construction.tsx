import { Hammer } from "lucide-react";

import { EmptyState } from "./empty-state";
import { PageHeader } from "./page-header";

/** Placeholder for routes whose full screen is being built in the current frontend pass. */
export function UnderConstruction({ title, note }: { title: string; note?: string }) {
  return (
    <div>
      <PageHeader title={title} />
      <EmptyState
        icon={Hammer}
        title="Being built in this pass"
        description={note ?? "This screen is part of the current frontend build and lands shortly."}
      />
    </div>
  );
}

/** FE-Records — upload, connect, and manage the customer record datasets the AI verifies against.
 * Datasets are validated synchronously by the backend (the FE renders that report verbatim);
 * connectors pull records live from an API or database. Mounted at `/admin/records`. */

import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/app/providers";
import { hasPermission } from "@/lib/rbac";

import { getRecordsSchema, listDatasets } from "./api";
import { ConnectorForm } from "./ConnectorForm";
import { RecordTypeCard } from "./RecordTypeCard";

export function RecordsPage() {
  const { role } = useAuth();
  const schemaQ = useQuery({ queryKey: ["records", "schema"], queryFn: getRecordsSchema });
  const datasetsQ = useQuery({ queryKey: ["records", "datasets"], queryFn: listDatasets });

  const header = (
    <PageHeader
      title="Records"
      description="Upload or connect the customer data your AI verifies against — orders, warranties, appointments, and more. Nothing leaves your tenant."
    />
  );

  if (role && !hasPermission(role, "records:manage")) {
    return (
      <div>
        {header}
        <EmptyState
          icon={Lock}
          title="You don't have access to records"
          description="Managing customer records requires the admin role. Ask a workspace admin if you need access."
        />
      </div>
    );
  }

  const schemas = schemaQ.data ?? [];
  const datasets = datasetsQ.data ?? [];
  const byType = new Map(datasets.map((d) => [d.record_type, d]));
  const loading = schemaQ.isLoading || datasetsQ.isLoading;

  return (
    <div>
      {header}

      {schemaQ.isError ? (
        <ErrorState
          title="Couldn't load the record schema"
          message="We couldn't fetch your tenant's record templates. Check your connection and try again."
          onRetry={() => schemaQ.refetch()}
        />
      ) : (
        <Tabs defaultValue="datasets" className="space-y-6">
          <TabsList>
            <TabsTrigger value="datasets">Datasets</TabsTrigger>
            <TabsTrigger value="connectors">Connectors</TabsTrigger>
          </TabsList>

          <TabsContent value="datasets" className="space-y-4">
            {loading ? (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-64 rounded-xl" />
                ))}
              </div>
            ) : schemas.length === 0 ? (
              <EmptyState
                title="No record types configured"
                description="Your tenant has no record templates yet. Once an industry template is set up, its datasets appear here."
              />
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {schemas.map((s) => {
                  const d = byType.get(s.record_type);
                  return (
                    <RecordTypeCard
                      key={s.record_type}
                      schema={s}
                      rowCount={d?.row_count ?? null}
                      updatedAt={d?.updated_at ?? null}
                    />
                  );
                })}
              </div>
            )}
          </TabsContent>

          <TabsContent value="connectors">
            {loading ? (
              <Skeleton className="h-96 rounded-xl" />
            ) : schemas.length === 0 ? (
              <EmptyState
                title="No record types to connect"
                description="Connectors map a live source onto a record template. Configure a record type first."
              />
            ) : (
              <ConnectorForm schemas={schemas} />
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

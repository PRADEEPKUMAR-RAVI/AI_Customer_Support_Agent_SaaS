/** FE-Records API wrappers over the typed client. */

import type { components } from "../../api/generated/schema";
import { api, unwrap } from "../../lib/api";

export type RecordSchemaOut = components["schemas"]["RecordSchemaOut"];
export type DatasetOut = components["schemas"]["DatasetOut"];
export type DatasetUploadReport = components["schemas"]["DatasetUploadReport"];
export type ConnectorIn = components["schemas"]["ConnectorIn"];
export type ConnectorOut = components["schemas"]["ConnectorOut"];
export type ConnectorTestReport = components["schemas"]["ConnectorTestReport"];
export type ConnectorListItem = components["schemas"]["ConnectorListItem"];
export type ConnectorDetail = components["schemas"]["ConnectorDetail"];
export type ConnectorPatchIn = components["schemas"]["ConnectorPatchIn"];
export type ConnectorValidateIn = components["schemas"]["ConnectorValidateIn"];

/** react-query key for the connector management list (distinct from datasets/schema keys). */
export const CONNECTORS_KEY = ["records", "connectors"] as const;

export async function getRecordsSchema(): Promise<RecordSchemaOut[]> {
  const { data, error } = await api.GET("/api/v1/records/schema", {});
  if (error) throw new Error("Failed to load record schema");
  return data ?? [];
}

export async function listDatasets(): Promise<DatasetOut[]> {
  const { data, error } = await api.GET("/api/v1/records/datasets", {});
  if (error) throw new Error("Failed to list datasets");
  return data ?? [];
}

export async function uploadDataset(recordType: string, file: File): Promise<DatasetUploadReport> {
  const { data, error } = await api.POST("/api/v1/records/datasets", {
    body: { record_type: recordType, file: file as unknown as string },
    bodySerializer() {
      const form = new FormData();
      form.append("record_type", recordType);
      form.append("file", file);
      return form;
    },
  });
  if (error) throw new Error("Dataset upload failed");
  return data!;
}

export async function deleteDataset(recordType: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/records/datasets/{record_type}", {
    params: { path: { record_type: recordType } },
  });
  if (error) throw new Error("Dataset delete failed");
}

export async function createConnector(body: ConnectorIn): Promise<ConnectorOut> {
  const { data, error } = await api.POST("/api/v1/records/connectors", { body });
  if (error) throw new Error("Connector save failed");
  return data!;
}

export async function testConnector(connectorId: string, testKey: string): Promise<ConnectorTestReport> {
  const { data, error } = await api.POST("/api/v1/records/connectors/{connector_id}/test", {
    params: { path: { connector_id: connectorId } },
    body: { test_key: testKey },
  });
  if (error) throw new Error("Connector test failed");
  return data!;
}

export async function listConnectors(): Promise<ConnectorListItem[]> {
  return unwrap<ConnectorListItem[]>(await api.GET("/api/v1/records/connectors", {}));
}

export async function getConnector(connectorId: string): Promise<ConnectorDetail> {
  return unwrap<ConnectorDetail>(
    await api.GET("/api/v1/records/connectors/{connector_id}", {
      params: { path: { connector_id: connectorId } },
    })
  );
}

export async function patchConnector(
  connectorId: string,
  body: ConnectorPatchIn
): Promise<ConnectorOut> {
  return unwrap<ConnectorOut>(
    await api.PATCH("/api/v1/records/connectors/{connector_id}", {
      params: { path: { connector_id: connectorId } },
      body,
    })
  );
}

export async function deleteConnector(connectorId: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/records/connectors/{connector_id}", {
    params: { path: { connector_id: connectorId } },
  });
  if (error) throw new Error("Connector delete failed");
}

/** Test-before-save: run one lookup against unsaved config without persisting. */
export async function validateConnector(body: ConnectorValidateIn): Promise<ConnectorTestReport> {
  return unwrap<ConnectorTestReport>(
    await api.POST("/api/v1/records/connectors/validate", { body })
  );
}

import { toIngestRequest, type GmailTransport } from './gmail';
import type { CaseSummary, IngestEmailRequest, IngestEmailResponse } from '../../frontend/src/api/types';

export interface CaseGateway {
  getCaseByMessage(token: string, id: string): Promise<CaseSummary>;
  ingestEmail(token: string, request: IngestEmailRequest): Promise<IngestEmailResponse>;
}
export async function analyzeEmail(id: string, token: string, gmail: GmailTransport, backend: CaseGateway): Promise<IngestEmailResponse> {
  const message = await gmail.getMessage(id);
  const request = await toIngestRequest(message, gmail.getAttachment);
  return backend.ingestEmail(token, request);
}

import type { Director } from '../lib/overlay.ts';
import { analysedCase, openCase, tab } from '../lib/flows.ts';

export const setup = analysedCase;

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await openCase(d, 'priya.qa', caseId);
  await tab(d, 'Label Check');
  const card = (b: string) => p.getByRole('tabpanel').locator('article').filter({ has: p.getByRole('heading', { name: b }) });
  await d.caption('05a', async () => { await d.spotlight(card('FG-1041'), 'HOLD + RELABEL'); await d.hold(3000); });
  await d.caption('05b', async () => { await d.spotlight(card('FG-1043'), 'CLAIM CONFLICT'); await d.hold(3000); await d.clearSpotlight(); });
}

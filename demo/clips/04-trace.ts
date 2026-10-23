import type { Director } from '../lib/overlay.ts';
import { analysedCase, openCase, tab } from '../lib/flows.ts';

export const setup = analysedCase;

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await openCase(d, 'priya.qa', caseId);
  await d.caption('04a', async () => {
    await tab(d, 'Batch Detective');
    const panel = p.getByRole('tabpanel');
    await d.spotlight(panel.getByRole('heading', { name: 'Material lot VL-2291' }), 'Lot VL-2291 · its 4 batches are listed below');
    await d.hold(3000);
    const last = panel.locator('article').filter({ hasText: 'FG-1043' });
    await d.scrollTo(last);
    await d.spotlight(last, 'FG-1043 · on shipment L-552');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}

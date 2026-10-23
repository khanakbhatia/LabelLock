import type { Director } from '../lib/overlay.ts';
import { approvals, approve, getCase } from '../lib/api.ts';
import { analysedCase, openCase, tab } from '../lib/flows.ts';

/** A contained case: analysed live, removal approved by the QA manager through the API. */
export async function setup() {
  const { caseId } = await analysedCase();
  const [removal] = await approvals();
  await approve(removal.id, 'Trace checked. Pull FG-1043 from L-552.');
  for (let i = 0; i < 40 && (await getCase(caseId)).status !== 'CONTAINED'; i++) await new Promise(r => setTimeout(r, 500));
  return { caseId };
}

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await openCase(d, 'priya.qa', caseId);
  await tab(d, 'Timeline');
  const panel = p.getByRole('tabpanel');
  await d.caption('10a', async () => {
    await panel.locator('article').first().waitFor();
    await d.spotlight(panel.locator('article').nth(1), 'Timestamp · event · actor');
    await d.hold(3000);
    await d.clearSpotlight();
  });
  await d.caption('10b', async () => {
    for (const [filter, label] of [['Decisions', 'Rules fired'], ['System calls', 'Every call to ERP, WMS and labels'], ['Actions', 'Approvals and verification attempts']]) {
      await d.click(p.getByRole('button', { name: filter, exact: true }), 700);
      await d.spotlight(panel.locator('article').first(), label);
      await d.hold(1500);
    }
    await d.clearSpotlight();
  });
}

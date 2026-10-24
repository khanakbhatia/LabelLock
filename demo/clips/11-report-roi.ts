import type { Director } from '../lib/overlay.ts';
import { approvals, approve, getCase } from '../lib/api.ts';
import { analysedCase, openCase } from '../lib/flows.ts';

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
  await openCase(d, 'daniel.qam', caseId);
  await d.caption('11a', async () => {
    await d.click(p.getByRole('button', { name: 'View report' }));
    const report = p.getByRole('region', { name: 'Case report' });
    await report.waitFor();
    await d.scrollTo(report);
    await d.spotlight(report, 'Per-batch outcome · time to containment');
    await d.hold(3000);
    await d.clearSpotlight();
  });
  await d.caption('11b', async () => {
    await d.click(p.getByRole('link', { name: 'ROI' }));
    const measured = p.getByRole('region', { name: 'Measured results' });
    await measured.waitFor();
    await d.spotlight(measured, 'MEASURED · 20 test scenarios');
    await d.hold(3000);
  });
  await d.caption('11c', async () => {
    const assumptions = p.getByRole('region', { name: 'Assumptions' });
    await d.scrollTo(assumptions);
    await d.spotlight(assumptions, 'ASSUMPTIONS · editable inputs, not results');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}

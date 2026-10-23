import type { Director } from '../lib/overlay.ts';
import { setup as containedCase } from './10-audit.ts';
import { openCase } from '../lib/flows.ts';

export const setup = containedCase;

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

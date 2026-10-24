import type { Director } from '../lib/overlay.ts';
import { analysedCase, openCase, tab } from '../lib/flows.ts';

export const setup = analysedCase;

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await openCase(d, 'priya.qa', caseId);
  await tab(d, 'Actions');
  await d.caption('06a', async () => {
    await d.spotlight(p.getByRole('row').filter({ hasText: 'Hold FG-1041 at DC-EAST' }), 'Placed automatically · VERIFIED');
    await d.hold(3000);
  });
  await d.caption('06b', async () => {
    await d.spotlight(p.getByRole('row').filter({ hasText: 'Remove FG-1043 from shipment L-552' }), 'PENDING APPROVAL · QA manager only');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}

import type { Director } from '../lib/overlay.ts';
import { getCase } from '../lib/api.ts';
import { APP, analysedCase, signedIn, tab } from '../lib/flows.ts';

export const setup = analysedCase;

export default async function (d: Director, { caseId }: Record<string, string>) {
  const p = d.page;
  await signedIn(d, 'daniel.qam', '/approvals');
  await d.caption('08a', async () => {
    const card = p.getByRole('region').filter({ hasText: 'Remove FG-1043 from shipment L-552' });
    await d.spotlight(card, 'Restricted action');
    await d.hold(1000);
    await d.clearSpotlight();
    await d.click(card.getByRole('button', { name: 'Approve' }));
    const dialog = p.getByRole('dialog');
    await d.type(dialog.getByLabel('Comment (optional)'), 'Pull FG-1043 from L-552.');
    await d.click(dialog.getByRole('button', { name: 'Confirm approve' }));
    await card.getByText('APPROVED').first().waitFor();
    await d.hold(600);
  });
  await d.caption('08b', async () => {
    for (let i = 0; i < 40 && (await getCase(caseId)).status !== 'CONTAINED'; i++) await d.hold(500);
    await p.goto(`${APP}/cases/${caseId}`);
    await tab(d, 'Actions');
    await d.spotlight(p.getByRole('row').filter({ hasText: 'Remove FG-1043 from shipment L-552' }), 'Executed and re-read · VERIFIED');
    await d.hold(3000);
    await d.clearSpotlight();
    await p.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
    await d.hold(600);
    await d.spotlight(p.getByText('CONTAINED').first(), 'Case CONTAINED');
    await d.hold(3000);
    await d.clearSpotlight();
  });
}

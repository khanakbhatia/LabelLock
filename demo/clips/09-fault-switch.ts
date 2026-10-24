import type { Director } from '../lib/overlay.ts';
import { signedIn } from '../lib/flows.ts';

export default async function (d: Director) {
  const p = d.page;
  await signedIn(d, 'admin', '/settings');
  await d.caption('09a', async () => {
    const sw = p.getByRole('switch', { name: 'WMS silently fails holds' });
    await sw.waitFor();
    await d.spotlight(sw, 'Test fault, injected by us');
    await d.hold(800);
    await d.click(sw);
    await p.waitForFunction(() => document.querySelector('[role=switch]')?.getAttribute('aria-checked') === 'true');
    await d.hold(1800);
    await d.clearSpotlight();
  });
}

import type { Director } from '../lib/overlay.ts';
import { card } from '../lib/flows.ts';

export default async function (d: Director) {
  await card(d.page, d, 'Act two · LabelLock in action', 'Recorded from the running product. AI calls are live.', 6);
}

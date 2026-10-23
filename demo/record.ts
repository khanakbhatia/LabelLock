/**
 * npm run demo:record [-- 03 06]   records every clip (or the listed ones) against the running app.
 *
 * Per clip: /api/demo/reset (fault off) -> optional setup through the product API -> capture the real UI in Edge
 * at 1600x900 with timestamped DevTools screencast frames -> real-time 1920x1080 MP4 (H.264, 30 fps, no audio) in
 * output/clips, checked against how long the clip ran. A take that throws
 * (for example a live run that did not produce the expected outcome) is discarded and retried.
 * Measured caption times are written back into captions.json.
 */
import { chromium, type BrowserContext, type Page } from 'playwright';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ffmpeg from 'ffmpeg-static';
import { CAPTIONS_PATH, Director, loadCaptions } from './lib/overlay.ts';
import * as api from './lib/api.ts';
import { Capture } from './lib/capture.ts';

interface Clip {
  setup?: () => Promise<Record<string, string>>;
  default: (d: Director, ctx: Record<string, string>) => Promise<void>;
}

const OUT = fileURLToPath(new URL('./output/', import.meta.url));
const CLIPS_DIR = new URL('./clips/', import.meta.url);
const wanted = process.argv.slice(2);
const files = readdirSync(CLIPS_DIR).filter(f => f.endsWith('.ts')).sort()
  .filter(f => !wanted.length || wanted.includes(f.slice(0, 2)));

mkdirSync(`${OUT}clips`, { recursive: true });

function mediaSeconds(file: string) {
  const m = spawnSync(ffmpeg as unknown as string, ['-hide_banner', '-i', file], { encoding: 'utf-8' }).stderr.match(/Duration: (\d+):(\d+):([\d.]+)/);
  if (!m) throw new Error(`cannot read duration of ${file}`);
  return +m[1] * 3600 + +m[2] * 60 + +m[3];
}
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const log: string[] = [];

for (const file of files) {
  const id = file.slice(0, 2);
  const clip: Clip = await import(new URL(file, CLIPS_DIR).href);
  for (let attempt = 1; ; attempt++) {
    const tmp = `${OUT}tmp-${id}`;
    rmSync(tmp, { recursive: true, force: true });
    let context: BrowserContext | undefined, page: Page | undefined;
    try {
      await api.reset();
      await api.setFault(false);
      const ctxData = clip.setup ? await clip.setup() : {};
      context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
      page = await context.newPage();
      if (process.env.LL_DEBUG) page.on('framenavigated', f => { if (f === page!.mainFrame()) console.log('  nav ->', f.url()); });
      await Director.attach(page);
      const capture = new Capture(tmp);
      await capture.start(page);
      const d = new Director(page, id);
      await clip.default(d, ctxData);
      await d.hold(600);
      const endMs = Date.now(), scriptSeconds = (endMs - d.t0) / 1000;
      await capture.stop();
      await context.close();
      capture.build(`${OUT}clips/${file.replace('.ts', '.mp4')}`, d.t0, endMs);
      const outSeconds = mediaSeconds(`${OUT}clips/${file.replace('.ts', '.mp4')}`);
      if (Math.abs(outSeconds - scriptSeconds) > 0.4) throw new Error(`clip is ${outSeconds.toFixed(2)} s but ran ${scriptSeconds.toFixed(2)} s: out of sync`);
      const caps = loadCaptions();
      for (const t of d.timings) Object.assign(caps.find(c => c.clip === id && c.id === t.id)!, { start: t.start, end: t.end, position: t.position });
      writeFileSync(CAPTIONS_PATH, JSON.stringify(caps, null, 1) + '\n');
      log.push(`${file}: ok on attempt ${attempt}, ${outSeconds.toFixed(2)} s (in sync)`);
      console.log(log.at(-1));
      break;
    } catch (e) {
      console.log(`${file}: attempt ${attempt} discarded - ${(e as Error).message.split('\n')[0]}`);
      await page?.screenshot({ path: `${OUT}fail-${id}-attempt${attempt}.png` }).catch(() => {});
      await context?.close().catch(() => {});
      if (attempt >= 3) { log.push(`${file}: FAILED after 3 attempts`); break; }
    } finally {
      try { rmSync(tmp, { recursive: true, force: true }); } catch { /* Windows may hold the file briefly */ }
    }
  }
}
await api.setFault(false);
await browser.close();
writeFileSync(`${OUT}record-log.txt`, log.join('\n') + '\n');
console.log(log.join('\n'));

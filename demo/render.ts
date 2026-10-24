/**
 * npm run demo:render   builds the final videos from output/clips/*.mp4 and captions.json (no re-recording).
 *
 * - Caption images: each caption is laid out in the browser (IBM Plex Sans 500, 36 px, white on
 *   rgba(12,16,20,.82), 10 px radius, max 2 lines) and saved as a transparent 1920x1080 PNG.
 * - Captioned clips: PNGs composited over each clip at their recorded times with a 250 ms fade.
 * - Joined: 0.4 s crossfades, H.264, 1920x1080, 30 fps, no audio track. Captioned and clean versions.
 * - labellock-act2.srt and voiceover-script.md with the final timecodes.
 */
import { chromium } from 'playwright';
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ffmpegPath from 'ffmpeg-static';
import { loadCaptions, type Caption } from './lib/overlay.ts';

const FF = ffmpegPath as unknown as string;
const OUT = fileURLToPath(new URL('./output/', import.meta.url));
const XFADE = 0.4;
const FADE = 0.25;
const CARD_TEXT: Record<string, { action: string; text: string }> = {
  '00': { action: 'Opening card: "Act two · LabelLock in action" + disclosure', text: '(on-screen card)' },
  '14': { action: 'Closing card: LabelLock statement + disclosure', text: '(on-screen card)' },
};

const duration = (file: string) => {
  const err = spawnSync(FF, ['-hide_banner', '-i', file], { encoding: 'utf-8' }).stderr;
  const m = err.match(/Duration: (\d+):(\d+):([\d.]+)/);
  if (!m) throw new Error(`no duration for ${file}`);
  return +m[1] * 3600 + +m[2] * 60 + +m[3];
};
const ff = (args: string[]) => execFileSync(FF, ['-y', '-hide_banner', '-loglevel', 'error', ...args], { stdio: 'inherit' });
const tc = (s: number, sep = ',') => {
  const ms = Math.round(s * 1000), h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, sec = Math.floor(ms / 1000) % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}${sep}${String(ms % 1000).padStart(3, '0')}`;
};
const short = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

const clips = readdirSync(`${OUT}clips`).filter(f => f.endsWith('.mp4') && existsSync(new URL(`./clips/${f.replace('.mp4', '.ts')}`, import.meta.url))).sort();
if (!clips.length) throw new Error('no recorded clips in output/clips - run npm run demo:record first');
const captions = loadCaptions();
const missing = captions.filter(c => c.start == null && clips.some(f => f.startsWith(c.clip)));
if (missing.length) throw new Error(`captions without recorded times: ${missing.map(c => c.id).join(', ')}`);

// 1. caption images
const imgDir = `${OUT}captions`;
rmSync(imgDir, { recursive: true, force: true });
mkdirSync(imgDir, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
for (const c of captions) {
  await page.setContent(`<!doctype html><html><head>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@500&display=swap" rel="stylesheet">
    <style>html,body{margin:0;background:transparent}
    .wrap{position:absolute;left:0;right:0;${c.position === 'top' ? 'top:150px' : 'bottom:74px'};display:flex;justify-content:center}
    .cap{max-width:1500px;padding:16px 28px;border-radius:10px;background:rgba(12,16,20,.82);color:#fff;
      font:500 36px/1.32 'IBM Plex Sans',sans-serif;text-align:center}</style></head>
    <body><div class="wrap"><div class="cap" id="cap">${esc(c.text)}</div></div></body></html>`);
  await page.evaluate(() => document.fonts.ready);
  const lines = await page.evaluate(() => { const el = document.getElementById('cap')!; const st = getComputedStyle(el);
    return Math.round((el.clientHeight - parseFloat(st.paddingTop) - parseFloat(st.paddingBottom)) / parseFloat(st.lineHeight)); });
  if (lines > 2) throw new Error(`caption ${c.id} wraps to ${lines} lines (max 2): shorten it in captions.json`);
  await page.screenshot({ path: `${imgDir}/${c.id}.png`, omitBackground: true });
}
await browser.close();

// 2. captioned clips
const capDir = `${OUT}captioned`;
mkdirSync(capDir, { recursive: true });
const durations: Record<string, number> = {};
for (const file of clips) {
  const id = file.slice(0, 2), src = `${OUT}clips/${file}`, dur = duration(src);
  durations[file] = dur;
  const mine = captions.filter(c => c.clip === id);
  if (!mine.length) { ff(['-i', src, '-c', 'copy', `${capDir}/${file}`]); continue; }
  const inputs = ['-i', src];
  const filters: string[] = [];
  let last = '0:v';
  mine.forEach((c, i) => {
    const s = c.start!, e = Math.min(c.end!, dur);
    inputs.push('-framerate', '30', '-loop', '1', '-t', dur.toFixed(2), '-i', `${imgDir}/${c.id}.png`);
    filters.push(`[${i + 1}:v]format=rgba,fade=in:st=${s}:d=${FADE}:alpha=1,fade=out:st=${Math.max(s, e - FADE)}:d=${FADE}:alpha=1[c${i}]`);
    filters.push(`[${last}][c${i}]overlay=0:0:enable='between(t,${s},${e})'[v${i}]`);
    last = `v${i}`;
  });
  ff([...inputs, '-filter_complex', filters.join(';'), '-map', `[${last}]`, '-t', dur.toFixed(2),
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30', '-an', `${capDir}/${file}`]);
}

// 3. joined videos with crossfades
const offsets: Record<string, number> = {};
let acc = 0;
clips.forEach((f, i) => { offsets[f] = acc; acc += durations[f] - (i < clips.length - 1 ? XFADE : 0); });
const total = acc;
const join = (dir: string, out: string) => {
  const inputs = clips.flatMap(f => ['-i', `${dir}/${f}`]);
  const norm = clips.map((_, i) => `[${i}:v]fps=30,scale=1920:1080,format=yuv420p,settb=AVTB[n${i}]`);
  const chain: string[] = [];
  let last = 'n0';
  for (let i = 1; i < clips.length; i++) {
    const off = (offsets[clips[i]]).toFixed(3);
    chain.push(`[${last}][n${i}]xfade=transition=fade:duration=${XFADE}:offset=${off}[x${i}]`);
    last = `x${i}`;
  }
  ff([...inputs, '-filter_complex', [...norm, ...chain].join(';'), '-map', `[${last}]`, '-c:v', 'libx264', '-preset', 'medium',
      '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '30', '-an', '-movflags', '+faststart', `${OUT}${out}`]);
};
join(capDir, 'labellock-act2-captioned.mp4');
join(`${OUT}clips`, 'labellock-act2-clean.mp4');

// 4. SRT and voiceover script with final timecodes
const placed = (c: Caption) => {
  const file = clips.find(f => f.startsWith(c.clip))!;
  return { start: offsets[file] + c.start!, end: offsets[file] + c.end! };
};
const ordered = captions.filter(c => clips.some(f => f.startsWith(c.clip))).sort((a, b) => placed(a).start - placed(b).start);
writeFileSync(`${OUT}labellock-act2.srt`, ordered.map((c, i) => {
  const t = placed(c);
  return `${i + 1}\n${tc(t.start)} --> ${tc(t.end)}\n${c.text}\n`;
}).join('\n'));

const rows: string[] = [];
for (const f of clips) {
  const id = f.slice(0, 2), start = offsets[f], end = start + durations[f];
  if (CARD_TEXT[id]) { rows.push(`| ${id} | ${short(start)} | ${short(end)} | ${CARD_TEXT[id].action} | ${CARD_TEXT[id].text} | |`); continue; }
  for (const c of ordered.filter(x => x.clip === id)) {
    const t = placed(c);
    rows.push(`| ${id} | ${short(t.start)} | ${short(t.end)} | ${c.action ?? ''} | ${c.text} | ${c.voice ?? ''} |`);
  }
}
writeFileSync(`${OUT}voiceover-script.md`, `# LabelLock act two - voiceover script

Final timecodes in \`labellock-act2-captioned.mp4\` / \`labellock-act2-clean.mp4\` (same picture). Total ${short(total)}.
Clips overlap by ${XFADE} s at each crossfade. The suggested lines are a starting point; read them to the timecodes.

| Clip | Start | End | On-screen action | Caption | Suggested spoken line |
|---|---|---|---|---|---|
${rows.join('\n')}

## Clip durations
${clips.map(f => `- ${f}: ${durations[f].toFixed(2)} s (starts at ${short(offsets[f])})`).join('\n')}
`);

console.log(`total ${total.toFixed(2)} s`);
for (const f of clips) console.log(`${f}  ${durations[f].toFixed(2)} s  @ ${short(offsets[f])}`);

import { readFile, writeFile, cp, mkdir, rm } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const extensionDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const frontendDir = resolve(extensionDir, '../frontend');
const { build } = createRequire(resolve(frontendDir, 'package.json'))('esbuild');
const apiBase = process.env.EXT_API_BASE_URL || 'http://localhost:8000/api';
const origin = new URL(apiBase).origin;
const manifest = JSON.parse(await readFile(resolve(extensionDir, 'manifest.json'), 'utf8'));
manifest.host_permissions = ['https://mail.google.com/*', 'https://gmail.googleapis.com/*', `${origin}/*`];
manifest.oauth2.client_id = process.env.EXT_OAUTH_CLIENT_ID || manifest.oauth2.client_id;
if (!process.env.EXT_OAUTH_CLIENT_ID) console.warn('EXT_OAUTH_CLIENT_ID is unset. The bundle builds, but Gmail sign-in needs Anvi’s Chrome extension OAuth client ID.');
// run vite's JS entry with node: node_modules/.bin/vite is a shell script that Windows cannot spawn directly
const vite = spawnSync(process.execPath, [resolve(frontendDir, 'node_modules/vite/bin/vite.js'), 'build', '--mode', 'panel'], {
  cwd: frontendDir, stdio: 'inherit', env: { ...process.env, VITE_APP_MODE: 'panel', VITE_USE_MOCKS: 'false', VITE_API_BASE_URL: apiBase },
});
if (vite.status !== 0) process.exit(vite.status || 1);
const dist = resolve(extensionDir, 'dist');
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await cp(resolve(extensionDir, 'panel'), dist, { recursive: true, force: true });
for (const name of ['background', 'content']) {
  await build({ entryPoints: [resolve(extensionDir, `src/${name}.ts`)], outfile: resolve(dist, `${name}.js`), bundle: true, format: 'iife', platform: 'browser', target: 'chrome116', minify: true });
}
await writeFile(resolve(dist, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log(`Load unpacked extension from ${dist}`);

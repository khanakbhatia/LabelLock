# LabelLock Chrome side panel

Build from `frontend/` after `npm ci`:

```bash
EXT_OAUTH_CLIENT_ID='your Chrome extension OAuth client ID' EXT_API_BASE_URL='http://localhost:8000/api' npm run build:panel
```

Load unpacked from `extension/dist` in `chrome://extensions`. The build reads `extension/manifest.json`, inserts the OAuth client ID and API origin, and bundles the shared React app plus the background/content scripts. The public manifest key fixes the extension ID at `ldpjjeldddhapjcjcncaefagfdlfojgp`; send that ID to Anvi before she creates the Chrome extension OAuth client. The OAuth client ID is public configuration, but don't commit account tokens. If the client ID is unset, the bundle builds but Gmail authorization cannot work.

The panel uses the backend at `EXT_API_BASE_URL`, not mock LabelLock data. Configure the backend's `EXTENSION_ORIGIN` as `chrome-extension://ldpjjeldddhapjcjcncaefagfdlfojgp` and enable CORS for that origin. The backend must be reachable from Chrome. OAuth grants only `gmail.readonly`.

Run the unit tests with `cd frontend && npm test`. Follow `docs/extension-manual-test.md` for the Chrome check.

# Clip 13 (Gmail) - manual recording checklist

Clip 13 was **not recorded automatically**. The Chrome extension cannot sign in to Google yet:
`extension/manifest.json` still has `"client_id": "REPLACE_WITH_EXT_OAUTH_CLIENT_ID.apps.googleusercontent.com"`
and `EXT_OAUTH_CLIENT_ID` in `.env` is empty. Google sign-in is never automated and no password is stored.

## One-time setup (Google Cloud, about 30 minutes, from the build plan D2)
1. In Google Cloud, project `labellock-demo`: enable the Gmail API.
2. OAuth consent screen: External, Testing, add the demo Gmail account as a test user, scope `gmail.readonly` only.
3. Load the extension unpacked once (`chrome://extensions` > Developer mode > Load unpacked > `extension/`) and copy its
   ID. The fixed `key` in the manifest keeps the ID stable.
4. Create an OAuth client of type **Chrome extension** with that ID. Put the client ID in `extension/manifest.json`
   (`oauth2.client_id`) and `EXT_OAUTH_CLIENT_ID` in `.env`; rebuild the panel as `extension/README.md` describes.
5. Backend: set `EXTENSION_ORIGIN=chrome-extension://<extension id>` in `.env` and restart it (CORS).

## Before recording
- [ ] Backend running with `LLM_MODE=live` (or say "AI responses replayed from a recorded live run" if mock).
- [ ] As admin, Settings > Reset demo (fault switch off).
- [ ] From another mailbox, send the demo Gmail account an email from an address that maps to Valley Ingredients
      (add it to `backend/dev_seed/suppliers.json` as an exact address, never `gmail.com`), subject
      `Lecithin source change from lot VL-2291`, the body from `backend/tests/fixtures/notices/vl2291_body.txt`,
      and `RM-114_spec_rev4.pdf` attached.
- [ ] Screen recorder at 1920x1080, 30 fps, no audio. Hide bookmarks and other tabs; use a clean Chrome profile.

## Recording (target 15-20 s)
1. Gmail open, supplier email visible. Click the LabelLock toolbar icon: the side panel opens.
2. Sign in to LabelLock in the panel as `priya.qa` / `demo` (Google sign-in already done off camera, by hand).
3. The panel shows the email card (sender, subject, PDF). Click **Analyze with LabelLock**.
4. The panel opens the new case. Click **Run agent**, wait for AWAITING APPROVAL.
5. Click Analyze again on the same email: it must open the **same** case (duplicate detection).
6. Hold on the case for 3 s.

Suggested captions (add to `captions.json` as clip `13` if you composite it into the cut):
- "The same case, inside Gmail: analyze a supplier email without leaving the inbox."
- "Analyze it twice and you get the same case, never a duplicate."

Banner to keep visible: "Demo: synthetic Northfield data; read-only Gmail access."

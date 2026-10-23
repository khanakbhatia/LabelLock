# LabelLock extension manual test

1. Ask Anvi to register extension ID `ldpjjeldddhapjcjcncaefagfdlfojgp` as a Chrome extension OAuth client and provide `EXT_OAUTH_CLIENT_ID`. Add the demo Gmail account as a test user. Configure the backend CORS `EXTENSION_ORIGIN` to `chrome-extension://ldpjjeldddhapjcjcncaefagfdlfojgp`.
2. In `frontend/`, run `npm ci`, then `EXT_OAUTH_CLIENT_ID='…' EXT_API_BASE_URL='http://localhost:8000/api' npm run build:panel` (replace both values). Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select `extension/dist`.
3. Open the dedicated demo Gmail account at `https://mail.google.com/`. Click the LabelLock toolbar icon. Confirm the side panel opens beside Gmail and shows the synthetic-data/read-only banner.
4. Sign in to LabelLock as `priya.qa` with password `demo`. Grant only Gmail read-only access when Chrome prompts. Confirm **Recent supplier emails** shows up to ten inbox PDF messages. Select one and check sender, subject and PDF names.
5. Open the supplier email in Gmail. Confirm the panel selects it if Gmail's DOM ID verifies; if not, confirm the fallback notice appears and select it from the recent list.
6. For a new message, click **Analyze with LabelLock**. Confirm the panel opens `/cases/:id`. If the case is still `RECEIVED`, click **Run case analysis**, then **Refresh case** to see extraction, trace and actions. A second selection of the same Gmail message should offer **Open case**. Repeating the ingest request should return `duplicate: true` and the same case ID.
7. As `daniel.qam`, open **Approvals** and approve a pending action. Confirm its status changes or leaves the pending queue. As `priya.qa`, click **Attempt approval (permission check)** and confirm the backend `403 FORBIDDEN` message and request ID appear. Do not treat a hidden UI button as proof of authorization.

   Current backend note: `GET /approvals` is not implemented and `POST /actions/{id}/approve` returns `501 NOT_IMPLEMENTED`. Record this as blocked until Anvi's approval endpoints land; the frontend mock tests exercise the intended behavior, not live approval.
8. Check a non-PDF email, a PDF over 5 MB, disconnected backend, and revoked Gmail access. Record the error text and request ID where provided. Reload the panel and verify LabelLock session restoration from `chrome.storage.session`; close Chrome to confirm the session token is not persistent.

Record Chrome version, extension ID, backend URL, Gmail account used, case IDs and any failing step. This script needs a real Chrome profile, Gmail OAuth client and backend; automated tests cannot replace it.

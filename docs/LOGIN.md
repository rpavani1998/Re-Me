# Sign in to Re:Me

## Email and password

Start the backend and dashboard, open http://localhost:3000, and choose **Create an account**. Use an email and a password of at least 12 characters. No API token is needed. Accounts have separate memories; existing token-based demo memories remain under the original user and are not automatically assigned to a new account.

The backend hashes passwords with salted scrypt. It stores only SHA-256 hashes of random session credentials. Sessions expire after 30 days and survive API restarts. The dashboard stores its session in this browser's local storage. **Account settings → Sign out** revokes that session. Email verification and password recovery are not implemented yet. Authentication attempts are limited per client IP, per API process; a public deployment needs an ingress/shared rate limiter across replicas.

## Continue with Google

1. In [Google Cloud Auth Platform](https://console.cloud.google.com/auth/clients), configure the consent screen and create an OAuth client with application type **Web application**. If the app is in testing, add your Google account as a test user.
2. Add `http://localhost:3000` to **Authorized JavaScript origins**. Add your deployed dashboard origin for a hosted deployment. This uses Google's popup ID-token flow; no redirect URI or client secret is needed.
3. Set `GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com` in `backend/.env` and restart the backend. Install updated backend requirements first. The dashboard fetches this public client ID from the backend; no separate frontend environment variable is needed.
4. Refresh the sign-in page. **Continue with Google** now appears.

The API verifies Google's signature, audience, expiry, issuer and verified-email claim. Existing password accounts must first sign in with their password, then link the same Google email under **Account settings**. Google accounts are identified by their stable `sub`, not by email alone.

References: [Google client setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid), [server-side token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

## Chrome extension

Reload the extension in `chrome://extensions` after updating its files. Open its settings and click **Sign in to Re:Me**. This opens the dashboard, where either login method works. Click **Connect extension** to finish; then return to any normal webpage and choose **Remember this page**.

The dashboard issues a separate session for the extension. A ten-minute, one-time handshake checks the initiating extension's random state and the dashboard origin before accepting it. Signing out of the extension revokes its session and clears local context. Signing out of the dashboard leaves the extension's independent session active.

Local URLs are already configured. For deployment, enter the dashboard and backend URLs in **Advanced connection settings**. Sign-in requests access to those origins and registers a content-script bridge for the dashboard. It does not require the webpage to expose `chrome.runtime` or a manifest edit for each hosted origin. Add that dashboard origin to backend `ALLOWED_ORIGINS` and Google's authorized origins too.

## Database deployment

Local development creates the new `accounts` and `login_sessions` tables at startup. For production, run `.venv/bin/python -m app.migrate` from `backend/` before deploying the API revision. This adds tables without deleting existing memories. Demo reset preserves accounts and login sessions.

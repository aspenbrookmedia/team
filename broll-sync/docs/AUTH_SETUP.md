# Google sign-in for the B-roll sync (one time, as founders@stylst.co)

Identity: **founders@stylst.co**. The program refuses to run if the token belongs to any other account.
Cost: none. The Drive API is free and needs no billing. Do not enable billing.

Project name to use: `stylst-broll-sync` (Google Cloud project, created while signed in as founders@stylst.co)
OAuth client: type **Web application**, name `broll-sync-github`
Permission requested: `https://www.googleapis.com/auth/drive`
Why this wide scope: the footage was not created by this app, so the narrower `drive.file` scope cannot see it.
What the code does with it: lists folders/files and creates shortcuts only. It never moves, edits, deletes, or re-shares anything.

Steps (screen labels in Google's console change; the links are stable):
1. Create project: https://console.cloud.google.com/projectcreate
2. Enable Drive API: https://console.cloud.google.com/apis/library/drive.googleapis.com
3. Consent screen / audience: https://console.cloud.google.com/auth/overview
   - Choose **Internal** if offered (stylst.co is a Google Workspace domain). Nothing to publish; tokens do not expire in 7 days.
   - If only **External** is offered, STOP and ask Claude. External apps left in "Testing" lose access every 7 days, and
     moving to "In production" is a publishing-status change that needs Aspen's approval first.
4. Data access: add the scope above.
5. Create the client: https://console.cloud.google.com/auth/clients
   Authorized redirect URI: `https://developers.google.com/oauthplayground`
6. Get the refresh token on Google's own page: https://developers.google.com/oauthplayground
   Gear icon -> "Use your own OAuth credentials" -> paste client ID and secret. Step 1: enter the scope above ->
   Authorize APIs -> sign in as founders@stylst.co and Allow -> Step 2: Exchange authorization code -> copy the refresh token.
7. Save three GitHub Actions secrets (repo Settings > Secrets and variables > Actions):
   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`.
   Never paste these into chat, issues, or files.

Revoke any time: https://myaccount.google.com/permissions (as founders@stylst.co), and delete the three secrets.

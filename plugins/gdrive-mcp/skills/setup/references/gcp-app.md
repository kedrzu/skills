# Creating the Google Cloud app (OAuth client)

Every Google account signs in through an OAuth client that belongs to a Google Cloud
project. One client serves any number of accounts and projects. Typical setups:

- **Personal assistant** — your own Cloud project, audience *External*, for `@gmail.com`
  and other accounts outside a company.
- **Company** — a Cloud project inside the company's Google Workspace, audience
  *Internal*: only accounts of that Workspace can sign in, nothing needs verifying, and
  colleagues reuse the same client.

**Already set up gmail-mcp?** The same Cloud project and the same Desktop client work for
Drive: enable the Google Drive API in that project (step 2) and reuse the client file.
Each account still signs in to gdrive-mcp separately, because the two plugins keep their
tokens apart.

The console calls the OAuth part **Google Auth Platform** (formerly "OAuth consent
screen"). Menu names drift; the steps stay the same.

## Steps

1. **Project.** console.cloud.google.com → project picker → *New project*. For an
   Internal app, create it under the company organisation (signed in with a Workspace
   account).
2. **Drive API.** *APIs & Services → Library* → "Google Drive API" → *Enable*.
3. **Branding / consent screen.** *Google Auth Platform → Get started*: app name (shown on
   the consent screen, e.g. "Acme Drive MCP"), support email, then the audience:
   - **Internal** — only offered to Workspace organisations. Use it for company accounts.
   - **External** — everything else. See "External apps" below before going further.
4. **Client.** *Google Auth Platform → Clients → Create client* → application type
   **Desktop app** → name it → *Create* → **Download JSON**
   (`client_secret_<…>.apps.googleusercontent.com.json`). A Desktop client needs no
   redirect URI: the sign-in returns to a random `127.0.0.1` port.
5. **Data access (optional).** Adding the scope the server asks for
   (`https://www.googleapis.com/auth/drive`) documents it; the consent screen asks for it
   either way. The full scope is deliberate: one sign-in serves every project, and each
   project's `permissions` decide what the agent may actually do.

Then return to the setup skill and choose where the downloaded file lives (repo, an
encrypted `.env`, or `client import` into the user's store).

## External apps: the 7-day trap

An External app starts in **Testing** status:

- only the addresses listed under *Audience → Test users* can sign in (max 100);
- **refresh tokens expire after 7 days** — every account has to sign in again each week.

For lasting access click *Audience → Publish app* (status **In production**). The `drive`
scope is *restricted*, so Google will not verify the app for public use without a
security assessment — but an unverified app in production works for its owner: the consent
screen shows "Google hasn't verified this app", you click *Advanced → Go to <app>
(unsafe)*, and the token no longer expires. The cap is 100 users, which is plenty for
personal use.

Internal apps have neither limit.

## Web-application clients

An existing *Web application* client works too, provided one of its authorised redirect
URIs is a loopback address with a port (e.g. `http://localhost:4002/oauth2callback`): the
sign-in then listens on exactly that port and path. Prefer a new Desktop client.

## Troubleshooting sign-in

| Message | Cause | Fix |
|---|---|---|
| `org_internal` / "This app is restricted to users within its organization" | Internal app, account outside the Workspace | Use the account's own client (personal app) |
| `access_denied` on an External app in Testing | Address not on the test-user list | Add it under *Audience → Test users*, or publish the app |
| "Google hasn't verified this app" | External app in production, unverified | Expected for personal use: *Advanced → Go to <app>* |
| `redirect_uri_mismatch` | Web client without a matching loopback redirect | Create a Desktop client |
| `invalid_grant` later on | Token expired (Testing: 7 days), revoked, or the password changed | Sign in again with `auth` |
| `invalid_client` | Client deleted or its secret rotated | Download the client again and update its source |
| Admin blocks the app | Workspace admin restricts third-party apps | Admin console → *Security → API controls*: mark the app as trusted |

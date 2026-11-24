# Public distribution: identity, server access, and quotas

The normal Settings screen deliberately omits the FastAPI address and the old shared developer bearer token. **That alone does not secure a public desktop application.** Users can inspect or modify any executable and its network calls. A publisher URL is not a secret; a shared token or Gemini key in the app would be extractable.

## Current status

The existing Northflank FastAPI service requires `COACH_ACCESS_TOKEN`; this is appropriate for private development/testing. Keep this setting in place. A packaged public build intentionally does **not** use that token. The default `src/release-config.json` has a blank publisher URL and `authentication: "not-configured"`, so a public build fails closed rather than exposing access.

The current implementation **does not yet include user sign-in or per-user quotas**, and must not be advertised as a production-ready public client. Setting `authentication` to `user-accounts` changes only the release-configuration guard. It does NOT add login, validate accounts or enable quotas.

## Recommended release architecture

1. **Account authentication.** Use a trusted OIDC identity provider (for example, Supabase Auth or another provider supporting OAuth 2.0/OIDC). Open login in the user's default browser with authorization-code + PKCE; do not embed a client secret. Use a registered loopback or deep-link callback.
2. **Short-lived user credentials.** Electron may store a *user-specific* refresh token via a secure OS credential store, but never ship a shared admin/service token. If the keyring is unavailable, require sign-in again rather than using Electron's insecure Linux basic_text fallback.
3. **FastAPI verification.** The backend must validate user access tokens using the provider's current JWKS: signature, allowed algorithms, issuer, audience, expiry, and revocation/session rules where supported. Derive the account ID from verified claims, not a client-provided field.
4. **Per-account and per-IP limits.** Rate-limit and quota on a shared persistent store (Redis or managed service) **before** calling Gemini. Add an upper bound on requests and Gemini spend; reject oversized requests and enforce concurrency caps. In-memory limits alone are not reliable across replicas.
5. **Publisher endpoint.** Set the production HTTPS FastAPI origin in `desktop/src/release-config.json` during packaging. This URL is safe to expose. Do not put `COACH_ACCESS_TOKEN` or `GEMINI_API_KEY` there, in Electron resources, the installer, GitHub, or the renderer.
6. **Abuse prevention and observability.** Do not trust API calls merely because they come from the desktop app. Verify identity and quotas on every request, monitor error/rate-limit activity, and avoid logging credentials or users' editing questions by default.
7. **Security testing.** Verify that missing/expired/forged tokens fail with 401, one user cannot use another's session, quota limits return 429, and a packaged app contains no service tokens. Test login/refresh/logout across Windows, macOS and Linux.

## Developer mode is separate

For private testing, use:

```bash
cd desktop
EDITING_HELPER_DEV_SETTINGS=1 npm start
```

This flag only enables the local connection controls in an **unpackaged** build. It does not bypass FastAPI authentication and cannot enable developer settings in packaged builds.

**Do not** remove FastAPI authentication or embed your existing shared `COACH_ACCESS_TOKEN` as a workaround to ship an installer.

# Security policy

## Supported versions

Möbius is a single-tenant self-hosted application. Only the latest commit on `main` is supported. There are no versioned releases with backport patches.

## Reporting a vulnerability

Please use [GitHub's private vulnerability reporting](https://github.com/hamzamerzic/mobius/security/advisories/new) to report security issues. Do not open a public issue.

Include:
- A description of the issue and affected component
- Steps to reproduce
- Your assessment of severity and exploitability

You can expect an acknowledgement within 72 hours. If the issue is confirmed, a fix will be committed to `main` and credited to you in the commit message unless you prefer otherwise.

---

## Known accepted trade-offs

Möbius is designed for a single owner deploying on their own VPS. The threat model is an external attacker, not a malicious co-tenant. The following issues are known, understood, and accepted given that context.

### JWT in localStorage

Auth tokens are stored in `localStorage`. This is accessible to any JavaScript running on the page. The accepted risk: you are the only person using this app, on your own device, on a domain you control. If you are concerned, use a dedicated browser profile.

### JWT in `?token=` query parameter

The session JWT is appended as a query parameter to iframe `src` URLs and attachment URLs (e.g. `?token=<jwt>`). This means the token appears in Caddy access logs, browser history, and `Referer` headers sent to the esm.sh CDN when mini-apps load dependencies.

Accepted because: logs are on your own server, browser history is on your own device, and the token expires after 8 hours. The fix (server-side token injection or short-lived scoped tokens) requires significant rework of the frame auth flow and is deferred.

### `null` CORS origin allowed

Sandboxed iframes without `allow-same-origin` send `Origin: null`. The API explicitly allows this origin so that mini-apps can make storage API calls. This means any sandboxed iframe on the internet could pass CORS preflight — but still requires a valid JWT to do anything useful.

Accepted because: without this, mini-apps cannot persist data, which breaks the core use case. The fix (routing mini-app API calls through a postMessage relay in the parent shell) is a large architectural change and is deferred.

### DNS rebinding in proxy SSRF protection

The proxy route (`/api/proxy`) validates the target URL by resolving its hostname and checking it is not a private IP. The actual HTTP request then resolves the hostname independently via `httpx`. A short-TTL domain controlled by an attacker could serve a public IP during validation and a private IP during the request.

Accepted because: exploiting this requires a compromised DNS server or a domain the attacker controls with sub-second TTL manipulation, and the proxy is only accessible to the authenticated owner. The fix (binding the resolved IP directly into the `httpx` request) is transport-level plumbing that is deferred.

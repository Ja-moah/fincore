# Security review

FinCore demonstrates security controls appropriate to a backend challenge. It
is not presented as production-ready.

## Implemented controls

- JWT parsing and signing use maintained libraries; there is no custom crypto.
- API permissions default to authenticated, with health and schema access made
  public intentionally for evaluation.
- The sender comes from authenticated ownership, never from client input.
- Transaction list/detail queries are ownership-scoped; unrelated details are
  returned as `404`.
- Structured errors suppress stack traces and database connection details.
- `.env` is excluded from Git, while `.env.example` contains development-only
  placeholders.
- `SECRET_KEY` is required at startup. JWT may use a separate signing key.
- `ALLOWED_HOSTS`, HTTPS redirect, secure cookies, HSTS, and the email backend
  are environment controlled. Defaults are suitable only for local development.
- Request IDs are validated UUIDs. Logs include correlation and outcome but not
  passwords, JWTs, authorization headers, request bodies, or account balances.
- Database constraints, atomicity, row locks, and idempotency protect financial
  integrity independently of API validation.

No CORS middleware is installed, so browsers receive no permissive cross-origin
policy by default.

The public evaluator staging environment intentionally contains predictable
fictional demo credentials. They are not production credentials and must be
removed by disabling `SEED_DEMO_ON_START` before adapting FinCore to any real
deployment.

## Production hardening required

- Set `DEBUG=False`, rotate strong application/JWT secrets through a secret
  manager, and restrict `ALLOWED_HOSTS` to deployment domains.
- Terminate TLS at a trusted proxy and enable HTTPS redirect, secure cookies,
  HSTS, proxy SSL headers, and CSRF trusted origins as appropriate.
- Restrict Swagger/schema access or publish a sanitized schema separately.
- Add rate limiting, credential-stuffing protection, refresh-token rotation or
  revocation, and short token lifetimes aligned with risk policy.
- Use a least-privilege database role, encrypted connections, managed backups,
  point-in-time recovery, high availability, and restore testing.
- Add dependency and container scanning, signed images, patch management, and
  protected CI environments.
- Protect audit data with separate permissions and tamper-evident external
  retention. Current application-level append-only intent is insufficient for
  regulated evidence.
- Add fraud controls, transaction limits, sanctions/risk review, reconciliation,
  and operational incident procedures.

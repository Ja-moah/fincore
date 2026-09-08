# Deployment

FinCore is designed for one stateless Django/Gunicorn service backed by one
managed PostgreSQL database. The deployment platform should terminate HTTPS,
route traffic to the application's `PORT`, and run the build, migration, and
start phases separately.

```text
Internet -> Django/Gunicorn service -> managed PostgreSQL
```

## Required environment variables

| Variable | Purpose | Example |
| --- | --- | --- |
| `SECRET_KEY` | Strong Django secret supplied by a secret manager | generated secret |
| `JWT_SIGNING_KEY` | Separate strong JWT signing key | generated secret |
| `DATABASE_URL` | Hosted PostgreSQL connection URL | `postgresql://user:pass@host:5432/db?sslmode=require` |
| `ALLOWED_HOSTS` | Comma-separated deployed hostnames | `fincore.example.com` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated HTTPS origins for admin/browser POSTs | `https://fincore.example.com` |
| `DEBUG` | Must be `False` | `False` |
| `EMAIL_BACKEND` | Production mail backend required by deploy checks | `django.core.mail.backends.smtp.EmailBackend` |
| `SEED_DEMO_ON_START` | Load the challenge dataset during startup | `true` for evaluator staging only |

`DATABASE_URL` must use PostgreSQL; the application rejects other database
engines. Local Docker Compose continues to use `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST`, and `DB_PORT` when `DATABASE_URL` is absent.

Recommended hosted settings are:

```dotenv
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=False
TRUST_PROXY_SSL_HEADER=True
DB_CONN_MAX_AGE=60
PORT=8000
WEB_CONCURRENCY=2
GUNICORN_THREADS=2
GUNICORN_TIMEOUT=30
```

Only enable `TRUST_PROXY_SSL_HEADER` when the hosting platform overwrites the
`X-Forwarded-Proto` header from untrusted clients. Enable HSTS gradually and
only enable preload after the domain and all subdomains are permanently ready.

## Release workflow

Prefer distinct platform phases where the host provides a release command.
Render deployments without Shell access may use the included startup script,
which applies non-interactive migrations and, for evaluator staging, loads the
idempotent demo dataset before starting Gunicorn.

**Build**

```bash
python -m pip install --disable-pip-version-check -r requirements.txt
python manage.py collectstatic --noinput
```

The supplied Dockerfile performs both steps while building the image.

**Migrate (release/pre-deploy phase)**

```bash
python manage.py migrate --noinput
```

Apply migrations once per release before directing traffic to code that depends
on them. Back up the database and review migration operations before production
rollout; do not run migration commands concurrently from every web replica.

**Start**

```bash
sh bin/start.sh
```

The script runs `python manage.py migrate --noinput`, loads demo data when
`SEED_DEMO_ON_START` is enabled, and only starts Gunicorn if both commands
succeed. Gunicorn binds to `0.0.0.0:${PORT:-8000}` and defaults to two threaded
workers with two threads each, a modest profile for a small staging service.
Tune concurrency against the service memory limit and PostgreSQL connection
budget.

This startup migration fallback is appropriate for FinCore's single staging web
service. Before scaling to multiple replicas, move migrations into the hosting
platform's one-off release/pre-deploy phase so several containers cannot attempt
schema changes simultaneously.

## Evaluator endpoints and demo data

- Transaction console: `GET /`
- Health check: `GET /health/`
- Swagger UI: `GET /api/docs/`
- OpenAPI schema: `GET /api/schema/`

The health response exposes only availability state, never connection details
or exception messages. Point the hosting health check at `/health/`.

The evaluator deployment creates fictional demo accounts at startup. The same
idempotent command can be run intentionally in another disposable environment:

```bash
python manage.py seed_demo
```

The command creates the publicly documented `Admin`, `Justice`, `Ama`, and
`Kojo` credentials from README.md. Disable `SEED_DEMO_ON_START` outside the
challenge staging environment and never run it against real financial data.

## Security and operations

- Store application, JWT, and database credentials in the platform secret
  manager; never put them in an image or repository.
- Require TLS to PostgreSQL when the provider supports it, use a least-privilege
  database role, and restrict network access to the application service.
- Keep `DEBUG=False`, restrict `ALLOWED_HOSTS`, and review whether public schema
  and Swagger access are appropriate beyond evaluation.
- Swagger UI and admin assets are collected into the image and served by
  WhiteNoise; the evaluator documentation has no runtime CDN dependency.
- Configure managed backups, point-in-time recovery, monitoring, log retention,
  dependency/container scanning, and secret rotation before real use.
- The container runs as an unprivileged `fincore` user and contains no runtime
  secrets. Supply all runtime credentials through environment variables.

## Rollback

Prefer forward-compatible, additive migrations followed by a code deployment.
For an application rollback, redeploy the preceding immutable image only when
its code remains compatible with the current schema. Do not blindly reverse a
migration containing data loss or irreversible operations. If a release alters
data incompatibly, stop writes, restore a verified managed-database backup or
apply a reviewed corrective migration, and validate ledger invariants before
restoring traffic.

# Result Portal Key Management

This guide covers the secrets used by `result_server/app.py`.

## Required Secrets

Production deployments must provide:

- `FLASK_SECRET_KEY`: at least 32 characters, generated randomly.
- `RESULT_SERVER_KEYS`: one or more runner-scoped ingest keys.

Use runner-scoped server keys instead of the legacy server-side
`RESULT_SERVER_KEY` fallback:

```text
RESULT_SERVER_KEYS=runner-a:<RUNNER_A_KEY>,runner-b:<RUNNER_B_KEY>
```

`RESULT_SERVER_KEYS` is the server-side registry of accepted posting/query
keys. It is intentionally broader than the current single-key CI setup so that
the portal can later accept results from multiple trusted CI sources, such as
the main BenchKit CI, site-managed runners, collaborator forks, or
estimator-only pipelines.

Each client job still receives a single `RESULT_SERVER_KEY` secret for its own
uploads. This client-side key must match one entry in `RESULT_SERVER_KEYS`, and
it is typically injected through GitLab CI/CD variables or another CI secret
mechanism rather than stored on the runner host.

Each key must be at least 32 characters and must not use known insecure
examples such as `dev-api-key`, `changeme`, or `secret`. The production app
refuses to start when these checks fail.

## Generation

Generate random values with a local secret generator, for example:

```bash
openssl rand -hex 32
```

Do not commit generated values. Store them in the deployment secret mechanism,
such as a systemd `EnvironmentFile`, a site secret manager, or an internal
vault service.

## Rotation

For a normal runner key rotation:

1. Add the new key to `RESULT_SERVER_KEYS` while keeping the old key.
2. Deploy the portal configuration.
3. Update the corresponding CI secret so affected jobs receive the new
   client-side `RESULT_SERVER_KEY`.
4. Confirm successful ingest events for the runner.
5. Remove the old key after the agreed overlap window.

If a key may have leaked, remove it immediately, deploy the portal, update the
affected CI secret, and review ingest logs for suspicious activity.

## Logging

Logs may include runner ids and endpoint names. They must not include API key
values, TOTP codes, or Flask secret values.

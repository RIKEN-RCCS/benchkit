# Result Portal Key Management

This guide covers the secrets used by `result_server/app.py`.

## Required Secrets

Production deployments must provide:

- `FLASK_SECRET_KEY`: at least 32 characters, generated randomly.
- `RESULT_SERVER_KEYS`: one or more runner-scoped ingest keys, or
  `RESULT_SERVER_TRUSTED_PROXY_AUTH=mtls` when nginx verifies client
  certificates before proxying ingest/query API requests.

Use runner-scoped server keys instead of the legacy server-side
`RESULT_SERVER_KEY` fallback:

```text
RESULT_SERVER_KEYS=runner-a:<RUNNER_A_KEY>,runner-b:<RUNNER_B_KEY>
```

`RESULT_SERVER_KEYS` is the server-side registry of accepted posting/query
keys for deployments that still use shared API keys. Client jobs in mTLS mode
do not use `RESULT_SERVER_KEY` and do not send an `X-API-Key` header.

Each key must be at least 32 characters and must not use known insecure
examples such as `dev-api-key`, `changeme`, or `secret`. The production app
refuses to start when these checks fail.

## Client Certificate Mode

Deployments can avoid shared ingest keys by terminating TLS at a trusted reverse
proxy and requiring a client certificate for result API endpoints. Configure the
portal with:

```text
RESULT_SERVER_TRUSTED_PROXY_AUTH=mtls
```

In this mode `RESULT_SERVER_KEYS` and the legacy `RESULT_SERVER_KEY` may be
empty, provided nginx verifies the client certificate and forwards these headers
only to the local Flask backend:

```nginx
proxy_set_header X-Result-Server-Client-Verify $ssl_client_verify;
proxy_set_header X-Result-Server-Client-DN $ssl_client_s_dn;
proxy_set_header X-Result-Server-Client-Fingerprint $ssl_client_fingerprint;
```

The nginx location must reject requests unless `$ssl_client_verify` is
`SUCCESS`. Keep the backend bound to loopback or a Unix socket so clients cannot
bypass nginx and provide these headers themselves.

CI jobs can use host-managed certificates instead of GitLab CI/CD secret
variables by mounting them read-only into a self-managed runner container and
setting:

```text
RESULT_SERVER_CLIENT_CERT=/run/benchkit/result-server/client.crt
RESULT_SERVER_CLIENT_KEY=/run/benchkit/result-server/client.key
```

The upload/query helper scripts use these variables automatically and do not
send an `X-API-Key` header.

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

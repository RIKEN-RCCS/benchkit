# Result Portal Key Management

This guide covers the secrets used by `result_server/app.py`.

## Required Secrets

Production deployments using the built-in upload/query helper scripts must
provide:

- `FLASK_SECRET_KEY`: at least 32 characters, generated randomly.
- `RESULT_SERVER_TRUSTED_PROXY_AUTH=mtls` when nginx verifies client
  certificates before proxying ingest/query API requests. This is the expected
  mode for the built-in upload and query helper scripts.

The server still accepts runner-scoped shared keys for legacy or custom clients
that send `X-API-Key`. Use `RESULT_SERVER_KEYS`, not the legacy server-side
`RESULT_SERVER_KEY` fallback:

```text
RESULT_SERVER_KEYS=runner-a:<RUNNER_A_KEY>,runner-b:<RUNNER_B_KEY>
```

`RESULT_SERVER_KEYS` is only the server-side registry of accepted posting/query
keys for deployments that still use shared API keys. The built-in CI upload and
query helper scripts use mTLS, require `RESULT_SERVER_CLIENT_CERT` and
`RESULT_SERVER_CLIENT_KEY`, and do not send an `X-API-Key` header.

Each configured shared key must be at least 32 characters and must not use
known insecure examples such as `dev-api-key`, `changeme`, or `secret`. The
production app refuses to start when these checks fail.

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

For normal mTLS client certificate rotation:

1. Issue a new client certificate/key pair.
2. Install it on the self-managed runner host or mounted runner secret path.
3. Keep the paths exposed to jobs as `RESULT_SERVER_CLIENT_CERT` and
   `RESULT_SERVER_CLIENT_KEY`.
4. Confirm successful ingest/query events through nginx mTLS.
5. Remove the old certificate from the runner host and revoke it in the
   certificate authority or nginx trust bundle.

For legacy shared-key clients:

1. Add the new key to `RESULT_SERVER_KEYS` while keeping the old key.
2. Deploy the portal configuration.
3. Update the legacy/custom client that sends `X-API-Key`.
4. Confirm successful ingest events for the runner.
5. Remove the old key after the agreed overlap window.

If a key or client certificate may have leaked, revoke it immediately, deploy
the portal or nginx trust configuration, update the affected runner/client, and
review ingest logs for suspicious activity.

## Logging

Logs may include runner ids and endpoint names. They must not include API key
values, TOTP codes, or Flask secret values.

# GitHub Workflows

## Deployment Webhook

`.github/workflows/deploy-latest.yaml` runs after GitHub Container Registry
publishes `ghcr.io/yiivgeny/barcode-hub:latest`. The workflow waits until the
`latest` manifest is pullable and then sends a signed `POST` request to the
deployment webhook.

Configure these repository secrets in GitHub:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

- `DEPLOY_WEBHOOK_URL`: deployment endpoint to call after `latest` is available.
- `DEPLOY_WEBHOOK_SECRET`: shared GitHub webhook secret. The workflow signs the
  JSON request body with HMAC-SHA256 and sends it as
  `X-Hub-Signature-256: sha256=<hex>`.

The webhook request also includes:

- `X-GitHub-Event: registry_package`
- `X-GitHub-Delivery: <run_id>-<run_attempt>`
- `Content-Type: application/json`

The receiving side should validate `X-Hub-Signature-256` against the exact
request body using `DEPLOY_WEBHOOK_SECRET`.

Make sure the GHCR package is connected to this repository so the
`registry_package` event is delivered to this workflow.

# GitHub Workflows

## Deployment Webhook

`.github/workflows/deploy-latest.yaml` runs after the `Docker image` workflow
successfully completes for a `push` to `main`. The workflow waits until
`ghcr.io/yiivgeny/barcode-hub:latest` and
`ghcr.io/yiivgeny/barcode-hub:sha-<short-commit>` are both pullable and resolve
to the same manifest digest, then triggers the Coolify deploy webhook.

Configure these repository secrets in GitHub:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

- `DEPLOY_WEBHOOK_URL`: Coolify deploy webhook URL from the application's Webhook page.
- `DEPLOY_WEBHOOK_SECRET`: Coolify API token with the `deploy` permission.

The workflow calls Coolify as documented by Coolify's GitHub Actions guide:

```bash
curl --request GET "$DEPLOY_WEBHOOK_URL" \
  --header "Authorization: Bearer $DEPLOY_WEBHOOK_SECRET"
```

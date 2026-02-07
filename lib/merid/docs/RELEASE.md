# Release Instructions

This document describes how to create a release for MERID.

Prerequisites

- You have write access to the repository and can create tags and releases.
- CI secrets are configured (if you plan to publish Docker images or notify external services).

Steps

1. Run tests locally and ensure everything passes.

   ```bash
   python -m pytest -q
   ```

2. Regenerate committed schema artifacts (if any schema models changed):

   ```bash
   python -c "from web.schema_export import export_schemas; export_schemas('generated/schemas')"
   git add generated/schemas && git commit -m "chore: regenerate schemas" || true
   ```

3. Update `docs/CHANGELOG.md` under the `Unreleased` heading with a short summary of the release.

4. Bump the release version and create a git tag (example `v0.1.0`):

   ```bash
   git tag -a v0.1.0 -m "Release v0.1.0"
   git push origin v0.1.0
   ```

5. Create a GitHub release (via the UI or `gh` CLI):

   ```bash
   gh release create v0.1.0 --title "v0.1.0" --notes-file docs/CHANGELOG.md
   ```

6. If you publish Docker images, update CI secrets and the Docker image workflow to push the image on release tags.

Publishing to GitHub Container Registry (GHCR)

This repository includes a workflow that publishes a Docker image to GHCR when you push a tag matching `v*.*.*` (`.github/workflows/publish-on-tag.yml`). It uses the repository's `GITHUB_TOKEN` to authenticate with GHCR and will tag the image both with the release tag and `latest`.

SBOM and image signing

The workflow now generates a CycloneDX SBOM for the released image using `syft` and uploads it as a workflow artifact. If you want the SBOM attached directly to the release, update the workflow to call the Releases API and upload the `sbom.json` artifact.

If you want to sign images, add a Base64-encoded private key to the repository secrets named `COSIGN_PRIVATE_KEY` (keep this secure!). When present the workflow will decode this key and run `cosign sign` to produce a signature for the published image. You may also want to add `COSIGN_PASSPHRASE` or a KMS-backed signer instead of storing the raw key in secrets.

To use a different registry (Docker Hub, ECR, etc.), replace the login and the `docker/build-push-action` credentials with the appropriate secrets (e.g., `DOCKER_USERNAME` / `DOCKER_PASSWORD`).

1. Announce the release to stakeholders and update any deployment manifests or infra pipelines.

Notes

- For safer releases, consider creating a release branch (e.g., `release/v0.1`) and running an integration test matrix before tagging.
- If you want automated CHANGELOG generation, consider using tools like `git-cliff` or `towncrier` in the pipeline.

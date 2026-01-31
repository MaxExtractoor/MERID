# MERID Infrastructure & CI Audit

Summary
-------
This document summarizes immediate findings from a cursory review of CI workflows, Dockerfile, and related infra manifests, plus concrete remediation recommendations prioritized for safety and release readiness.

Findings
--------
- CI workflows reference signing and publish steps (cosign, GHCR). Ensure private keys are stored in Secrets Manager or KMS and not checked into workflows or checked-in encrypted blobs without clear rotation semantics.
- Several workflows include build and publish steps; check job permissions (GITHUB_TOKEN scopes) and restrict to least-privilege where possible.
- The `publish-on-tag.yml` workflow runs image signing with cosign; GH Actions should use ephemeral credentials and secrets should be scoped and masked.
- Nightly and production pipelines perform deployments and health checks; ensure they run in staging first and have separate deploy credentials.
- Dockerfile exposes Uvicorn binding and may use root user or large base image — consider multi-stage builds, smaller base image, non-root user, and explicit port exposure only needed for infra.
- No detect-secrets baseline present; CI now runs detect-secrets but creating a reviewed `.secrets.baseline` will avoid false positives while still failing on new secrets.
- No automatic vulnerability remediation bot configured (dependabot/snyk PRs) — consider enabling Dependabot for Python and Dockerfiles to get automated PRs for upgrades.

Immediate Remediations (high priority)
--------------------------------------
1. Secret handling
   - Ensure all signing keys (COSIGN_PRIVATE_KEY) and publish tokens are stored as GitHub Secrets or cloud KMS-managed secrets. Do NOT keep unencrypted keys in repo or workflow files.
   - Add `detect-secrets` baseline file (`.secrets.baseline`) to the repo after reviewing/clearing true positives.
   - Add a `pre-commit` hook (detect-secrets) to prevent accidental commits containing secrets.

2. CI permissions and least privilege
   - Audit the `permissions` block for each workflow and set explicit minimal permissions for tokens (e.g., `contents: read` vs `contents: write` only when necessary).
   - Use `environment` protections for deploy jobs (require approval for prod deployments).

3. Container hardening
   - Make Dockerfile multi-stage and use a minimal base (e.g., `python:3.11-slim` → thin runtime image), set a non-root `USER`, and reduce layer size.
   - Add SBOM and image signing steps (already present) but ensure cosign uses ephemeral keys or KMS integration.

4. Add automated dependency monitoring
   - Enable Dependabot or configure Snyk/GH Advisory-based PRs so upgrades are proposed automatically.

Medium / Nice-to-have
---------------------
- Add `trivy` scan step to CI for container image scanning.
- Add `pip-audit` and `bandit` to CI (done) and add a policy for triage timelines (fix within X days depending on severity).
- Implement runtime secrets injection (Kubernetes Secrets, HashiCorp Vault) and avoid building secrets into images.

Next steps I will take (in order)
---------------------------------
1. Run the `vuln-scan` (pip-audit + bandit) and `secrets-scan` in CI (requires PR push) to collect concrete findings. I'll collate the results and create prioritized remediation issues.
2. Prepare a small PR that adds a `detect-secrets` baseline and a `pre-commit` config to block secrets on commit.
3. Propose a minimal Dockerfile hardening patch (multi-stage and non-root) for review.
4. Create issues for enabling Dependabot and Trivy in CI if you approve.

Contact / Notes
---------------
If you'd like, I can push these fixes and open draft PRs once you push the branch (you offered to push manually) — then CI will run the vuln & secrets scans and I'll act on the findings.

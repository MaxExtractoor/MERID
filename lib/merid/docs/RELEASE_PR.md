Release PR template for v0.1.0

Title: Release v0.1.0

Description:

- Summary: MERID v0.1.0: core orchestrator, trading & risk, admin lockdown, SBOM & signing-ready publish workflow, E2E harness, audit persistence.

Checklist:

- [ ] All tests pass
- [ ] CHANGELOG updated and `docs/CHANGELOG.md` includes v0.1.0
- [ ] VERSION file updated
- [ ] Release notes present (`RELEASE_NOTES.md`)
- [ ] CI secrets configured for GHCR and cosign if you plan to publish images
- [ ] Draft release created and artifacts attached (SBOM)

Notes:
Use the 'publish-on-tag' workflow to publish Docker images after pushing a tag matching `v*.*.*`.

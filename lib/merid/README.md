# merid

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Lab: Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Cookbook: Useful Flutter samples](https://docs.flutter.dev/cookbook)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

## Operator Controls & Frontend Safety

- The Flutter UI includes an **Operator Lockdown** toggle that disables interactive controls and input when the system is locked down.
- The app communicates with the backend admin endpoints (`GET /admin/lockdown` and `POST /admin/lockdown`) to read and set the server-wide lockdown flag.
- Admin endpoints require a bearer token from the `MERID_ADMIN_TOKEN` environment variable; in development the default token is `local-admin-token`.
- For local testing the Flutter UI will prompt for an admin token when toggling lockdown.

## Documentation & tooling

- See the `docs/` folder for additional documentation:
  - `docs/USAGE.md` — quick start and commands for local dev, schema generation and E2E sim
  - `docs/ARCHITECTURE.md` — high-level architecture overview
  - `CONTRIBUTING.md` — contribution guidelines
- Quick: run the E2E sim locally with a helper script:

```bash
python scripts/run_e2e.py --steps 20 --threshold 50
```


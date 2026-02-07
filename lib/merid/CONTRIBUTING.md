# Contributing to MERID

Thanks for contributing! A few quick guidelines to help keep contributions focused and reviewable.

## Repo layout & tests

- Run tests before submitting a pull request:

```bash
python -m pytest -q
```

- Keep changes small and accompanied by tests.

## Code style

- We use `ruff` for linting and basic formatting checks.

## Schema artifacts

- If you change Pydantic models in `web/schemas.py`, regenerate the JSON artifacts used by the frontend:

```bash
python -c "from web.schema_export import export_schemas; export_schemas('generated/schemas')"
```

Then commit the updated files.

## Notes on safety

- This project includes an operator lockdown mechanism and an in-memory audit log. When modifying execution flows, add appropriate audits and tests to keep actions traceable.

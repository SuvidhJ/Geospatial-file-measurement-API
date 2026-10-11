# Contributing

Thanks for helping improve the Geospatial File Measurement API. This guide covers local
setup, the checks every change must pass, and the conventions the codebase follows.

## Development setup

Requires Python 3.11+. The geospatial wheels bundle GDAL, GEOS and PROJ, so no system
libraries are needed.

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pre-commit install                 # run ruff, mypy and file checks on every commit
make run                           # http://localhost:8000
```

To run the full stack (API, Redis queue and worker): `docker compose up --build`.

## Checks

`make check` runs everything CI runs:

| Check | Command |
|---|---|
| Lint and formatting | `make lint` (ruff) |
| Types | `make typecheck` (mypy with `disallow_untyped_defs`) |
| Tests and coverage | `make test` (pytest; fails below 95% coverage) |

A pull request is ready when `make check` passes and the change has tests.

## Conventions

- **Layering.** Routes in `app/api/` only parse requests and shape responses. Logic lives in
  `app/services/`, which never imports FastAPI request objects and raises typed `AppError`s
  for client-facing failures.
- **Errors.** Every error response uses the envelope in `app/schemas/errors.py`. Add a new
  `AppError` subclass with a stable `code` instead of raising `HTTPException`.
- **Measurement code** (`crs.py`, `measure.py`, `volumes.py`) is pure functions over shapely
  geometries and arrays, testable without HTTP or a database.
- **Tests use independent ground truth.** Build expected values without the code under test:
  walk geodesics with `pyproj.Geod` for areas and lengths, use closed-form shapes (cones,
  planes) for volumes. Fixtures are generated in `tmp_path` by `tests/factories.py`.
- **Comments explain why, not what.** Prefer a clear name to a comment.
- **Numbers in the README come from running the code**: `make accuracy` for the accuracy
  table, the running app for example responses.

## Database migrations

The schema is managed with Alembic and applied on startup. After changing a model:

```bash
alembic revision --autogenerate -m "describe the change"
```

Review the generated file in `app/migrations/versions/`. `tests/test_migrations.py` fails if
the models and migrations drift apart.

## Sample data

Files in `sample_data/` are generated, never hand-edited:

```bash
make sample-data
```

Generation is deterministic, so an unchanged generator produces identical files.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
`test:`, `build:`, `refactor:`, `chore:`. Keep the subject under 72 characters and explain
the reason for the change in the body when it is not obvious.

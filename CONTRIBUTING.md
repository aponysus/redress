# Contributing

## Versioning

We follow Semantic Versioning (`MAJOR.MINOR.PATCH`):
- Breaking public API changes (e.g., `ErrorClass`, `RetryPolicy` signature, metric events/tags) → MAJOR
- Backwards-compatible features → MINOR
- Bug fixes and internal-only changes → PATCH

## Release process

1. Bump `version` in `pyproject.toml`.
2. Update `CHANGELOG.md` for the release.
3. Run quality gates locally: `uv run python -m ruff format --check src src/tests docs` (optional), `uv run python -m ruff check src src/tests docs`, `uv run python -m mypy src`, `uv run python -m pytest`.
4. Commit and tag: `git tag -a vX.Y.Z -m "Release X.Y.Z"` and push the tag.
5. (Optional) Build/publish: `uv build` (requires hatchling) and upload the wheel/sdist to your chosen index.

# Contributing

## Versioning

We follow Semantic Versioning (`MAJOR.MINOR.PATCH`):

- Breaking public API changes (e.g., `ErrorClass`, `RetryPolicy` signature, metric events/tags) → **MAJOR**
- Backwards-compatible features → **MINOR**
- Bug fixes and internal-only changes → **PATCH**

## Local development

1. Create / activate a virtualenv (if not already):

   ```bash
   uv venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   ```

2. Install the project in editable mode with dev dependencies:

   ```bash
   uv pip install -e .[dev]
   ```

3. (Optional) Install pre-commit hooks:

   ```bash
   uv run pre-commit install
   ```

4. Run the quality checks:

   ```bash
   # Formatting
   uv run ruff format --check src tests docs

   # Lint
   uv run ruff check src tests docs

   # Type checking
   uv run mypy src

   # Tests
   uv run pytest
   ```

## Release process

Releases are automated by GitHub Actions when a version tag is pushed.

### 1. Bump version and changelog

1. Update `version` in `pyproject.toml`.
2. Update `CHANGELOG.md` with a new section for the version.

### 2. Run quality gates

From the project root (venv activated):

```bash
uv run ruff format --check src tests docs
uv run ruff check src tests docs
uv run mypy src
uv run pytest
```

You can also run the same checks via pre-commit:

```bash
uv run pre-commit run --all-files
```

All of these should pass before releasing.

## Good first contributions

Low-friction contributions are useful here. Good starting points include:

- docs clarifications and wording fixes
- starter-kit or recipe improvements
- example maintenance and smoke-test coverage
- small classifier or contrib fixes with focused tests

If you open an issue, it helps to make the scope explicit:

- `bug` for defects in behavior
- `enhancement` for API or feature additions
- `docs` for documentation, recipes, examples, and starter kits

Small, well-scoped issues are easier to review and easier to release safely.

### 3. Tag the release

Tag and push the version:

```bash
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z
```

Pushing the tag triggers the release workflow to build distributions, create a GitHub
release, and publish to PyPI. This keeps git history in sync with the published
package versions.

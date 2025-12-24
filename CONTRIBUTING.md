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

We publish to TestPyPI first, then to PyPI.

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

### 3. Build distributions (wheel + sdist)

Install the build tooling into your venv if needed:

```bash
uv pip install build twine
```

Then build:

```bash
uv run python -m build
```

This should create:

```text
dist/
  redress-X.Y.Z.tar.gz
  redress-X.Y.Z-py3-none-any.whl
```

### 4. Upload to TestPyPI

1. Ensure you have a TestPyPI account and API token.
2. Upload:

   ```bash
   uv run python -m twine upload --repository testpypi dist/*
   ```

   When prompted:

   - Username: `__token__`
   - Password: your **TestPyPI** API token

3. In a fresh virtualenv, verify you can install and use the package:

   ```bash
   uv venv .venv-test
   source .venv-test/bin/activate

   uv pip install -i https://test.pypi.org/simple redress

   python -c "from redress import RetryPolicy"
   ```

   Deactivate the test env when done.

### 5. Upload to PyPI

1. Ensure you have a PyPI account and API token.
2. Upload from the main project venv:

   ```bash
   uv run python -m twine upload dist/*
   ```

   When prompted:

   - Username: `__token__`
   - Password: your **PyPI** API token

### 6. Tag the release

After a successful upload, tag and push:

```bash
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z
```

This keeps git history in sync with the published package versions.

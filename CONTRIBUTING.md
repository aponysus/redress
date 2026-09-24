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
   uv run ruff format --check src tests docs scripts

   # Lint
   uv run ruff check src tests docs scripts

   # Type checking
   uv run mypy src

   # Tests
   uv run pytest
   ```

## Release process

Releases are automated by GitHub Actions when a version tag is pushed.
The release gate supports stable `MAJOR.MINOR.PATCH` versions with tags named
`vMAJOR.MINOR.PATCH`. Pre-release version support requires an explicit update
to the gate and release process.

### 1. Prepare matching source versions

1. Update `version` in `pyproject.toml`.
2. Run `uv lock` to update the local project's version in `uv.lock`.
3. Add a dated `CHANGELOG.md` section for that version, with release notes.
   It must be the newest numbered release section; an `Unreleased` section
   may precede it.
4. Run `python scripts/check_release.py`.

PR CI checks these source versions and builds and checks both distributions.
Prepare the metadata and changelog together in the same change.

### 2. Run quality and artifact checks

From the project root (venv activated):

```bash
uv run ruff format --check src tests docs scripts
uv run ruff check src tests docs scripts
uv run mypy src
uv run pytest
python -m pip install build
python -m build
python scripts/check_release.py --dist dist
```

Use a fresh distribution directory. The artifact gate requires exactly one
wheel and one sdist, verifies their filenames and embedded package name/version,
and rejects stale or extra artifacts (`uv build`'s `.gitignore` is ignored).
`python -m build` builds the wheel from
the sdist by default, which also exercises the source distribution.

You can also run formatting, lint, and type checks through pre-commit:

```bash
uv run pre-commit run --all-files
```

### 3. Tag the verified commit

After committing and merging the release preparation, substitute the intended
version for `X.Y.Z`:

```bash
python scripts/check_release.py --tag vX.Y.Z --dist dist
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z
```

The release workflow verifies the tag against source versions before building,
then checks the built distribution metadata before publishing. Manual dispatch
must target a tag; a branch dispatch fails. Publication fails on existing PyPI
artifacts rather than silently skipping them. A GitHub release is created or
updated only after the PyPI publishing step succeeds.

After publication, verify the expected version is available from PyPI and that
the wheel and sdist have the expected version. Gates do not replace verifying
remote publication or running the quality checks for the release commit.

### Recovery from an existing incorrect tag or partial release

The review found that the existing `v1.4.1` tag describes 1.4.0 package metadata;
the maintainer confirmed PyPI still has 1.4.0. Correcting the working tree does
not repair that existing tag, and rerunning its old workflow uses the old code.

The chosen recovery is to release 1.4.2 and leave `v1.4.1` unchanged. The
1.4.2 changelog includes the unpublished fixes and documents the skipped PyPI
version. Validate the corrected commit and its artifacts with
`python scripts/check_release.py --tag v1.4.2 --dist dist` before tagging it.
Do not move the existing tag: downstream users may already reference it.
Preparing the version metadata does not itself tag or publish a release.

If PyPI upload succeeds but GitHub release creation fails, repair the GitHub
release separately after verifying the published artifacts. If only some
artifacts uploaded, inspect the remote files and local artifacts before any
recovery; do not re-enable blanket `skip-existing` to hide a mismatch.

## Project review

The [2026-09-24 codebase and documentation review](docs/reviews/2026-09-24-codebase-review.md)
records confirmed defects, integration risks, evidence, and recommended work.
Only its release-integrity finding is addressed by the accompanying gates;
other findings remain open.

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

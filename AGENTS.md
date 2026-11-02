# redress

## Purpose and boundaries

Policy-driven failure handling for Python services: a distributable library with
sync and async APIs and a configuration diagnostic CLI ([README.md](README.md),
[pyproject.toml](pyproject.toml)).

- Owns: exception/result classification, retry strategies and limits, retry
  budgets, circuit breakers, structured outcomes, lifecycle hooks, and optional
  client/framework/observability adapters.
- Excludes: application hosting, downstream service implementations, database
  schemas, durable queue scheduling, and application-specific idempotency.
  Callers supply operations and clients; deferred retries require an external
  scheduler (`src/redress/sleep.py`, `docs/recipes/workers.md`).

## Correctness and compatibility

- Preserve sync/async behavior across `Policy` / `AsyncPolicy`, retry components,
  wrappers, and decorators. `call()` returns results or raises; `execute()` exposes
  `RetryOutcome`. Cancellation and process-exit exceptions must propagate
  (`src/redress/policy/runner/`, `tests/test_async_policy.py`).
- `max_attempts` includes the initial call. Exhaustion must not compute another
  delay, consume another budget token, or invoke sleep hooks
  (`src/redress/policy/state.py`, `tests/test_terminal_attempt.py`).
- Deadlines bound retry decisions and sleeps, not in-flight execution. Sync
  attempt timeouts cannot terminate worker threads; async timeouts use
  `asyncio.wait_for`. Preserve unknown/per-class caps, strategy selection, and
  terminal stop reasons (`docs/performance-tuning.md`, `src/redress/policy/base.py`).
- Breakers observe final operation outcomes, not individual retry attempts.
  Budgets and breakers share state only within the process
  (`src/redress/policy/execution.py`, `src/redress/budget.py`, `src/redress/circuit.py`).
- Observability hooks are best-effort: ordinary hook exceptions must not alter
  workload outcomes. Attempt hooks must not swallow cancellation or process exit
  (`src/redress/policy/hooks.py`, `tests/test_attempt_hook_isolation.py`). Keep
  event names and tags compatible and low-cardinality (`src/redress/events.py`,
  `docs/observability.md`).
- Documented public APIs follow semantic versioning, including exception,
  outcome, hook, and stop-reason semantics. Deprecate before removal and wait at
  least two minor releases (`docs/stability.md`). Source versions in
  `pyproject.toml`, `uv.lock`, and the newest numbered `CHANGELOG.md` entry must
  agree; release tags and artifacts must match (`scripts/check_release.py`).

## Architecture and navigation

Entry points and components:

| Location | Responsibility |
| --- | --- |
| `src/redress/__init__.py`, `src/redress/policy/__init__.py` | Public exports; prefer `Policy(retry=Retry(...))` and the async equivalent for composition. |
| `src/redress/policy/policy.py`, `async_policy.py`, `execution.py` | Policy containers, breaker integration, and final outcomes. |
| `src/redress/policy/retry_sync.py`, `retry_async.py`, `runner/`, `state.py` | Retry execution; shared decisions in `runner/logic.py`, I/O in sync/async cores. |
| `src/redress/policy/wrappers.py`, `decorator.py`, `context.py` | Retry-only shortcuts, `@retry`, and reusable call contexts. |
| `src/redress/classify.py`, `errors.py`, `config.py`, `strategies.py`, `sleep.py` | Classification, error/stop contracts, configuration, backoff, and sleep/defer decisions. |
| `src/redress/budget.py`, `circuit.py`, `events.py`, `metrics.py` | Shared limits, breaker state, lifecycle events, and metric adapters. |
| `src/redress/extras/`, `src/redress/contrib/` | Thin classifiers and richer SDK, HTTP, framework, worker, and telemetry integrations. |
| `src/redress/testing/`, `tests/` | Deterministic testing helpers and behavioral regression tests. |
| `src/redress/cli.py` | `redress doctor module:attribute [--show]`; imports the target module to inspect a config/policy. |
| `scripts/check_release.py`, `.github/workflows/`, `mkdocs.yml` | Release checks, CI/publication, and documentation navigation/build. |

- External authoritative behavior: SDK exception types, response headers,
  SQLSTATE codes, framework lifecycles, and telemetry APIs come from downstream
  libraries/services. Adapter source and declared extras are local; downstream
  implementations, credentials, and live deployment configuration are not.
  This library has no repository-owned database or migration layer.

## Technology and conventions

- Runtime versions and dependency tooling: `pyproject.toml` declares Python
  `>=3.11`, no mandatory runtime dependencies, Hatchling builds, and optional
  dependency extras. `uv.lock` is committed. The `dev` extra contains the full
  development toolchain; the separate `dev` dependency group contains only Ruff.
- Repository conventions: source lives in `src/redress/`, tests in `tests/`,
  executable documentation examples in `docs/snippets/`. Mypy checks `src` using
  Python 3.12 semantics; Ruff uses a 100-character line length and `I` import rules
  (`pyproject.toml`).
- Runtime/deployment/platform constraints: metadata declares OS independence;
  CI jobs run on Ubuntu, with tests on Python 3.11–3.13. There is no Windows/macOS
  CI matrix or repository-wide development interpreter pin. Release and docs
  publishing are separate GitHub Actions workflows; PyPI publishing uses
  `PYPI_API_TOKEN`, while Pages uses GitHub permissions/OIDC. Local development
  does not require publishing credentials (`.github/workflows/`).

Use uv for dependency and environment management, pytest for tests, Ruff for
linting and import sorting, and the existing formatter hooks described below.
Keep configuration in `pyproject.toml` and commit `uv.lock`. Use a project-local
`.venv`, exclude it from version control, and run tools through `uv run`. Declare
runtime dependencies separately from development tools; do not depend on globally
installed packages.

Set `requires-python` to the supported interpreter range and keep any
`.python-version`, formatter targets, and CI versions consistent with it. Pin
the development interpreter deliberately without narrowing library support
accidentally. Review dependency changes and their lockfile diff together.

The existing `.pre-commit-config.yaml` runs Ruff lint/import fixes, Ruff format,
Black with `--line-length=100`, and mypy. It pins hook versions independently of
`uv.lock`. Isort is not configured; Black has no `[tool.black]` settings, so a
standalone Black invocation needs the line-length flag. Preserve this existing
toolchain; resolving overlapping formatters is a separate tooling change.
Use type hints throughout, built-in generics such as `list[str]`, and explicit
return types. Use Google-style docstrings for public APIs and non-obvious
contracts, including errors and side effects. Ruff is not a static type checker;
preserve mypy and its configuration.

## Development commands

Run from the repository root with uv and Python 3.11–3.13. Dependency installation
requires package-index access or a populated cache; pre-commit also needs its
hook environments. Select the `dev` extra explicitly: bare `uv sync` does not
install the full test/type-check toolchain.

Local commands using the existing configuration and lockfile:

```sh
uv sync --locked --extra dev
uv run --locked --extra dev pytest
uv run --locked --extra dev ruff check src tests docs scripts
uv run --locked --extra dev ruff format --check src tests docs scripts
uv run --locked --extra dev black --check --line-length=100 src tests docs scripts
uv run --locked --extra dev mypy src
uv run --locked --extra dev pre-commit run --all-files
uv run --locked python scripts/check_release.py
```

Pre-commit includes modifying hooks (`ruff --fix` and formatters); inspect its
diff. To apply formatting directly, use Ruff import/lint fixes and Ruff format,
then Black with `--line-length=100`, matching the hook order. Keep generated
build outputs and virtual environments outside these checks.

- Tests with all declared extras: `uv run --locked --all-extras pytest`.
  `.github/workflows/ci.yml` installs
  `.[dev,aiohttp,grpc,boto3,redis,urllib3,openai,anthropic]` with pip and runs pytest
  with coverage. Pytest defaults enable branch coverage with an 85% minimum.
  A focused development run can use
  `uv run --locked --extra dev pytest --no-cov tests/test_policy.py -k deadline`;
  retain coverage for the full suite.
- Documentation: `uv run --locked --extra docs mkdocs build --strict`.
- Benchmark: `uv run --locked --extra dev python docs/snippets/bench_retry.py`.
- CLI: `uv run --locked redress --help`, then
  `uv run --locked redress doctor module:attribute --show` for an importable
  config/policy object. Importing that target executes its module-level code.

`mise.toml` provides test, typecheck, lint, fmt, and all tasks, but does not select
the `dev` extra; provision dependencies first. Its lint/fmt tasks cover only
`src`, and `all` includes formatting. CI lint/type checks use pre-commit; direct
local commands may use different tool versions.

Use `uv add` and `uv remove` to change dependencies, preserving the existing
extra/group distinction. Use a deliberate lockfile update for upgrades; normal
checks use `--locked` so they do not silently resolve new versions. `uv run`
handles the project environment; a separate `python -m pip install .` step and
an installed pip module are unnecessary for this local workflow.

Preserve Hatchling. `uv build` builds distributions; CI uses `python -m build`
and `twine==7.0.0`. Validate a fresh artifact directory with
`python scripts/check_release.py --dist dist` and `python -m twine check --strict dist/*`
in an environment with those build tools, as described in `CONTRIBUTING.md`.
The artifact check requires exactly one wheel and one sdist. Verify the wheel
in an isolated environment outside the checkout before a release.

Distinguish commands found in configuration from commands actually run. Record
material environmental limits; never label an unrun command as verified.

## Verification and documentation

- Behavior and integration checks: `tests/test_policy.py`, `test_async_policy.py`,
  `test_wrappers.py`, and `test_retry_decorator.py` cover the public execution
  surfaces; `test_terminal_attempt.py` and `test_attempt_hook_isolation.py` protect
  terminal behavior and observer isolation. Budget, breaker, classification,
  strategy, event, and contrib tests cover their corresponding components.
  `test_strategies.py` includes Hypothesis properties; use `redress.testing`
  helpers for deterministic retry tests. `test_docs_examples_verified.py` exercises
  selected docs/snippets, and `test_release_consistency.py` tests release checks.
- Integration limits: optional SDK tests use `pytest.importorskip` when packages
  are absent; many contrib tests use fake clients/errors. Passing these tests
  does not establish live-service or real middleware compatibility. CI has no
  live-service provisioning. ODBC drivers/databases and telemetry backends are
  consumer-provided; pyodbc classification itself is dependency-free, and the
  default OpenTelemetry adapters require `opentelemetry-api`, which has no
  declared project extra (`src/redress/contrib/pyodbc.py`, `otel.py`).
- Authoritative documentation: update `README.md`, the relevant pages under
  `docs/`, and `CHANGELOG.md` when public behavior changes. Start with
  `docs/api.md`, `docs/design_notes.md`, `docs/stability.md`, and
  `docs/performance-tuning.md` for contracts; use `CONTRIBUTING.md` for contributor
  workflows and `.github/workflows/` for the commands automation actually runs.
  MkDocs navigation is in `mkdocs.yml`; `docs/changelog.md` includes the root
  changelog. Generated `site/` output is not the documentation source.

Write pytest tests around observable behavior, compatibility, and failure modes.
Use fixtures, parametrization, temporary directories, and controlled dependency
substitutes where they clarify the contract. Keep unit tests independent of
credentials, live services, wall-clock timing, and the developer's home directory.
Make integration-test dependencies and invocation explicit. Exercise cleanup,
cancellation, and partial failure where relevant; do not assert private details
merely to increase coverage.

Run focused checks during development, then the relevant project checks. Keep CI
and local commands aligned. Once those pass, repeat or expand verification only
for new changes or unresolved concerns. Update examples and public documentation
when behavior changes; report checks actually run and material limits.

Maintain project facts here after specialization. Preserve headings, section order,
and unrelated content. Subsequent instruction changes require explicit user
authorization for enduring requirements; do not record task progress here.

## Python context

- Supported interpreters: packaging accepts Python `>=3.11` with no upper bound;
  documented support and CI cover 3.11–3.13. Compatibility with newer interpreters
  and non-Ubuntu platforms is not established by the checked-in CI matrix
  (`pyproject.toml`, `docs/stability.md`, `.github/workflows/ci.yml`).
- Package/import layout: `src/redress/` is the installable package. Preserve
  documented exports in `src/redress/__init__.py` and `src/redress/policy/__init__.py`,
  plus public contrib/testing helpers; internal runner helpers are not public APIs.
- Import-time behavior constraints: core imports must work without optional
  SDKs. Extras lazily import dependencies and may fall back to the default
  classifier; contrib helpers may raise explicit missing-dependency errors on use
  (`src/redress/extras/boto3.py`, `src/redress/contrib/openai.py`).
- Distribution/runtime compatibility: Hatchling packages `src/redress` and
  explicitly includes `py.typed` in wheel and sdist. Keep the core dependency-free;
  preserve optional SDK bounds in `pyproject.toml` (OpenAI `>=1.40,<2`, Anthropic
  `>=0.40,<1`) and review adapter tests when changing them.

Prefer a `src/` layout for new distributable packages and a separate `tests/`
directory; preserve an established layout. Keep imports free of network access,
environment mutation, and other application startup work. Use context managers
for owned resources, propagate async cancellation, and catch specific exceptions
at boundaries where recovery or useful context can be added. Preserve public
signatures, exception behavior, serialized formats, and supported Python versions.

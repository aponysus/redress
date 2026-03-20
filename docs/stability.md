# Stability and compatibility

Use this page when you want to know what “stable” means for redress and how to
evaluate adoption risk.

## Stability promise

redress follows semantic versioning for `1.x` releases.

In practical terms:

- patch releases should not break documented behavior
- minor releases may add features and integrations, but should remain backward-compatible
- breaking changes require a major version

## What counts as breaking

Examples of breaking changes:

- removing a documented public API
- changing the meaning of a documented parameter or stop reason
- changing hook payload semantics in a way that breaks existing integrations
- changing documented retry or outcome behavior incompatibly

Examples that are not normally breaking:

- new optional parameters with safe defaults
- new contrib modules or examples
- expanded docs and recipes
- stricter internal validation that only rejects previously-invalid configuration

## Deprecation policy

When a public API needs to change:

- it should be deprecated in one release
- the deprecation should be documented
- removal should not happen earlier than two minor releases later

The goal is to keep downstream upgrades predictable.

## Support boundaries

### Core APIs

Strongest compatibility expectations apply to the core documented APIs:

- `Policy`, `AsyncPolicy`
- `Retry`, `AsyncRetry`
- `RetryPolicy`, `AsyncRetryPolicy`
- `CircuitBreaker`
- `RetryOutcome`
- classifiers, strategies, and documented hook contracts

### Extras

`redress.extras` modules are intentionally thin classifier adapters.

Compatibility expectations:

- the redress-facing behavior should remain stable
- third-party library changes may require small adapter adjustments over time
- extras are supported, but intentionally narrow in scope

### Contrib integrations

`redress.contrib` modules are supported public APIs built on top of the core
model.

Compatibility expectations:

- documented helper functions and wrappers should remain stable
- compatibility can be narrower than the core because external frameworks and
  clients evolve independently
- internal implementation details inside contrib modules are not the contract

## Python support

The project currently targets Python `3.11` through `3.13`.

Dropping a supported Python version is a compatibility-affecting change and
should not happen silently.

## Optional dependency policy

Optional integrations are kept dependency-light by design:

- no optional backend should be required for core usage
- extras and contribs should degrade gracefully where practical
- import-time failures for optional integrations should be explicit and local

## What downstream users should rely on

Safe assumptions:

- documented public APIs are the compatibility boundary
- stop reasons and hook/event semantics are intended to be stable
- sync and async APIs should preserve the same core semantics

Unsafe assumptions:

- internal helper functions inside modules
- undocumented implementation details
- exact internal structure of contrib integrations beyond the documented API

## Adoption guidance

If you want the lowest-risk adoption path:

1. depend on documented public APIs only
2. prefer the canonical `Policy(retry=Retry(...))` surface for new code
3. treat contrib integrations as convenience layers, not extension internals
4. pin optional third-party integrations responsibly in your own application

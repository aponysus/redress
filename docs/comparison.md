# Redress vs. Alternatives

This page explains how **redress** differs from other retry and failure-handling libraries in the Python ecosystem.

The goal is not to rank libraries, but to clarify **abstraction boundaries** so you can choose the right tool for your problem.
This is about *model and semantics*, not performance benchmarks or popularity.

---

## Summary

**redress is a failure-policy library.**
Retries and circuit breakers are coordinated responses to **classified failure**, not independent wrappers.

Most alternatives focus on **retry mechanics** (decorators, predicates, backoff math) or **single mechanisms** (retry *or* circuit breaking). redress focuses on making failure handling *explicit, bounded, and observable* across a codebase.

If you want a small retry helper, redress may be unnecessary.
If you want a shared failure-handling model that coordinates retries and breakers consistently, that’s where redress fits.

---

## Comparison at a glance

| Library / Model         | Core abstraction        | Classification                   | Result-based retries | Retry + breaker coordination | Outcome surface              | Typical use                              |
| ----------------------- | ----------------------- | -------------------------------- | -------------------- | ---------------------------- | ---------------------------- | ---------------------------------------- |
| **redress**             | Failure policy          | Semantic error classes           | **Yes**              | **Yes** (unified `Policy`)   | Typed stop reasons, outcomes | Coordinated failure handling in services |
| Tenacity                | Retry decorator         | Predicates on exceptions/results | Yes (predicate)      | No                           | Exception or return value    | General-purpose retries                  |
| Backoff                 | Retry decorator         | Exception types                  | No                   | No                           | Exception or return value    | Simple exponential backoff               |
| Stamina                 | Opinionated Tenacity    | Predicates (Tenacity)            | Yes (predicate)      | No                           | Exception or return value    | Safer defaults for Tenacity              |
| urllib3 / httpx retries | HTTP retry adapter      | HTTP status codes                | Limited              | No                           | HTTP response / exception    | HTTP client retries                      |
| PyBreaker / aiobreaker  | Circuit breaker wrapper | Exceptions                       | No                   | No                           | Exception                    | Standalone circuit breaking              |

---

## Tenacity

**What it is:**
A powerful, flexible retry decorator built around predicates, stop conditions, and backoff strategies.

**Strengths:**

* Extremely flexible
* Mature and widely used
* Works for both exceptions and return values

**Trade-offs:**

* Retry logic lives at the call site
* Classification is ad-hoc (predicates), not semantic
* Circuit breaking is out of scope
* No unified notion of *why* retries stopped beyond “predicate returned false”
* Result-based retries are possible, but still ad-hoc (predicate-driven)

**When Tenacity is a good fit:**

* You want fine-grained control over retry conditions
* Retries are local decisions
* You don’t need coordination with breakers or shared policy semantics

**How redress differs:**

* Classification is explicit and semantic (`ErrorClass`)
* Retry behavior is defined as *policy*, not scattered predicates
* Retry and breaker decisions share the same classification and observability
* Outcomes include explicit stop reasons, not just exceptions

---

## Backoff

**What it is:**
A lightweight decorator for exponential backoff on exceptions.

**Strengths:**

* Simple API
* Minimal configuration
* Easy to understand

**Trade-offs:**

* Exception-only
* Global backoff behavior
* No circuit breaking
* Limited observability

**When Backoff is a good fit:**

* You want a small amount of retry logic with minimal ceremony
* Failure handling is not central to your system design

**How redress differs:**

* Designed for bounded behavior under load
* Supports per-class behavior and result-based retries
* Provides structured outcomes and stop reasons

---

## Stamina

**What it is:**
An opinionated wrapper around Tenacity that provides safer defaults and better ergonomics.

**Strengths:**

* Production-oriented defaults
* Reduces common Tenacity foot-guns
* Familiar to Tenacity users

**Trade-offs:**

* Still fundamentally a retry decorator
* Classification remains predicate-based
* Circuit breaking remains out of scope

**When Stamina is a good fit:**

* You like Tenacity’s model but want safer defaults
* You don’t need retries to coordinate with other failure mechanisms

**How redress differs:**

* Moves beyond retry decorators into a shared policy model
* Coordinates retries and circuit breakers explicitly
* Outcomes include explicit stop reasons, not just exceptions

---

## urllib3 / httpx retry adapters

**What they are:**
HTTP-specific retry implementations based on status codes and retry counts.

**Strengths:**

* Well-understood semantics for HTTP
* Integrates directly into HTTP clients
* Familiar to many engineers

**Trade-offs:**

* HTTP-only
* Retry semantics are tightly coupled to the client
* Circuit breaking is external
* Limited visibility into retry *decisions*

**When they are a good fit:**

* You only care about HTTP retries
* You want client-level retry behavior with minimal setup

**How redress differs:**

* Not tied to HTTP
* Uses the same classification model for HTTP, databases, queues, etc.
* Coordinates retry decisions with breaker state and outcomes

---

## Circuit breaker libraries (PyBreaker, aiobreaker, etc.)

**What they are:**
Standalone circuit breaker wrappers.

**Strengths:**

* Focused and explicit
* Easy to layer on top of existing code
* Clear breaker semantics

**Trade-offs:**

* Retry logic is separate
* No shared classification model
* Observability and stop reasons differ from retries

**When they are a good fit:**

* You already have retry logic and just need a breaker
* Coordination between retries and breakers is not important

**How redress differs:**

* Breaker decisions are driven by the same classification as retries
* One policy governs both mechanisms
* Outcomes are unified and observable

---

## Choosing the right tool

Use **redress** if:

* You want retries and circuit breakers to share semantics
* You care about *why* failure handling stopped
* You want bounded behavior enforced consistently
* You prefer a shared policy over call-site glue

Use **Tenacity / Backoff / Stamina** if:

* Failure handling decisions are local to the call site
* You don’t need retry behavior to coordinate with circuit breakers
* Consistency across a codebase is handled by convention rather than enforcement

Use **HTTP client retries** if:

* You only care about HTTP
* Client-level retries are sufficient

Use **standalone circuit breakers** if:

* You only need breaker behavior
* Retry coordination is not required

---

## A note on philosophy

redress is intentionally opinionated.

It trades some flexibility for:

* explicit classification
* enforced bounds
* consistent outcomes
* coordinated failure responses

If that model resonates, redress will likely simplify your system.
If it doesn’t, the alternatives above are excellent tools.

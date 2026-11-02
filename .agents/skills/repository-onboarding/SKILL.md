---
name: repository-onboarding
description: Map an unfamiliar repository or multi-solution project and draft evidence-grounded AGENTS.md context for a new maintainer.
---

# Repository onboarding

Establish enough context to navigate and change the requested part of a repository safely.

## Method

1. Locate the requested root, existing instructions, and repository boundaries. Read applicable nested instructions before inspecting a subsystem. Confirm file access; do not infer a repository from a ticket alone.
2. Inventory manifests, solutions, packages, entry points, CI, and maintained documentation. Sample representative modules to trace responsibilities and dependencies; exhaustive reading is rarely useful.
3. Establish language/framework versions, dependency tooling, generated code, and build/test commands from actual files. Record each command's working directory and prerequisites. Distinguish a command found in configuration from one executed successfully.
4. Identify external services, databases, unavailable source, platform requirements, and runtime secrets by purpose without exposing values. Multiple solutions may require separate builds; opening a directory does not prove an IDE loaded them all.
5. Propose a concise repository map or `../../../AGENTS.md`, using the existing structure when present. Include durable invariants, navigation, commands, and boundaries. Mark unknown facts explicitly and remove irrelevant template sections.

## Result and stopping point

Provide source references for important facts, usable navigation, and the material unknowns that affect development. Stop when the requested area can be understood and the next safe development step is clear; do not expand into unrelated repositories.

Preview changes to an existing `../../../AGENTS.md` and write only within the user's authorized scope. Never edit production code or run destructive setup/migrations as onboarding. A scaffold alone does not establish project facts.

## Example

A synthetic tree contains `Legacy.sln` targeting .NET Framework and `Tools.sln` targeting modern .NET. Explain their separate entry points and Windows constraints. A test command found in CI remains documented-only until run in the required environment; do not report both solutions as locally verified.

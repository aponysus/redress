---
name: api-contract-evolution
description: Plan compatible changes to HTTP, gRPC, or message contracts, including fields, errors, validation, paging, authentication, and versioning.
---

# API contract evolution

Evaluate a change from the consumer's perspective, including mixed-version operation.

## Method

1. Read project instructions and inspect the actual wire schema, handlers, serializers, documentation, and contract tests. Establish defaults, omission versus null, status/error semantics, ordering, and authentication/authorization behavior relevant to the request.
2. Inventory known clients, generated code, stored messages, caches, and external consumers. Identify what cannot be inspected. Repository search alone cannot establish all deployed clients.
3. Compare old/new producers and consumers in both directions. An additive field or enum value can still break strict decoders or exhaustive consumers. Check request validation, pagination/filtering, retries, and error behavior when affected.
4. Prefer the smallest compatible evolution. Where a break is necessary, propose an explicit migration/version/deprecation approach and deployment order. Consider replay of old messages and rollback compatibility, not just the latest client/server pair.
5. Specify contract tests using old and new representations and consumer expectations. Include observable failure cases and telemetry that can reveal migration problems without exposing sensitive payloads.

## Result and stopping point

Return the proposed contract difference, concrete breaking cases, migration path, focused tests, and evidence gaps. Stop short of a compatibility guarantee when a material consumer is unavailable. Identify the consumer contract or test needed to settle it.

Analysis does not authorize deployment, external communication, or code edits; respect the user's existing implementation scope.

## Example

Changing `count: 0` to `count: null` may break a generated non-nullable client even though the field name is unchanged. Test the old decoder against the new payload and preserve the old representation or version the contract if the client cannot migrate first.

# Review a change

Establish the supplied diff, revision, or commit range and the requirements it should satisfy. If the review target is ambiguous, clarify it before choosing a range. Read project instructions and inspect affected callers, contracts, and tests.

Review in an independent session when feasible; selecting a role alone does not create independence. Prioritize reachable correctness, compatibility, security, data-loss, partial-failure, and resource-lifecycle defects. Use focused nondestructive checks when useful. Ignore stylistic preferences handled by existing tooling.

Compare the diff with the intended outcome, including omitted conditions and unsupported completion claims. Challenge suspicious changes to tests, verification, or acceptance criteria; distinguish legitimate test corrections supported by independent contract evidence and authorized scope.

Return findings ordered by impact and reachability, each with a precise location, concrete trigger, evidence, consequence, and smallest remedy. Distinguish demonstrated defects from uncertain concerns. State when no material issue is found, the exact scope reviewed, checks actually run, and material gaps. Do not modify source, tests, or instructions, and do not create a report file unless requested.

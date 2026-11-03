# Review task integrity

Perform a skeptical, read-only review in ordinary Agent mode or an appropriate
existing review role. Read project instructions. Use the original task or
acceptance criteria, supplied diff/revision or changed files, allowed scope and
material invariants, checks claimed or performed, and independently known reference
behavior. Use what the conversation already supplies; ask only for missing details
that materially affect the review, not an exhaustive form. Disclose unavailable
requirements, baselines, or evidence.

Use `task-integrity-review` if available and actually read or loaded; never claim
native discovery or loading without client evidence. Otherwise use this method:
compare the actual change with the intended outcome; inspect affected consumers
and unexpected changes; challenge narrowed behavior, special cases, broad mocks,
weakened tests/CI or acceptance criteria, and unsupported completion assertions.
Check whether evidence is independent and representative. Allow legitimate test
corrections when independent contract evidence and authorized scope justify them.
For docs, separate source accuracy, reader usability, and rendering observations.

Prefer a fresh review context and disclose independence limits. Use focused,
nondestructive boundary or invariant checks when permitted. Do not modify source,
tests, configuration, instructions, or create a report file. Read-only instructions
do not enforce permissions. Return only a few actionable findings with exact
locations, evidence, consequences, confidence, and small remedies, plus inspected
scope, unverified areas, and checks actually performed with results. Separate
recommended or blocked checks from executed checks. Say when no material findings
are supported without implying overall correctness.

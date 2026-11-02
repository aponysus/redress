# Characterize runtime behavior

Use Test Engineer or ordinary Agent mode. Establish the target behavior,
competing hypotheses, available reference environment, and allowed execution
authority from the request; ask for missing information that affects the design
or permission to execute. Use `runtime-characterization` and `test-design` when
available and actually read or loaded.

Design a small set of controlled experiments that distinguish the hypotheses
and cover meaningful boundaries. Specify version/build and data snapshot,
configuration, frozen input fixtures, preconditions/prior state, predicted
outcomes, output/log captures, run identity, permitted side effects and reset
conditions, and justified comparison rules. Keep data and evidence within
authorized storage. Do not introduce an export mechanism or runtime automation.

Without authorized live access, return the design rather than claim execution.
If results are supplied or authorized experiments run, compare actual outcomes
with source-derived expectations and prior reference results. Recommend narrow
updates to the same maintained documentation; mark only actual observations as
runtime-confirmed for their tested conditions. Distinguish parity with existing
behavior from independently established domain correctness, and retain
contradictions and inconclusive cases. Any real environment access or side
effect needs authorization covering that target and action; this prompt alone
does not grant it.

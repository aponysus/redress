---
name: diagram-review
description: Review Mermaid and other text-backed engineering diagrams for semantic fidelity and reader communication, inspecting renderings only when available.
---

# Diagram review

Establish the diagram, intended question/audience, allowed evidence, and available
rendering. Read applicable project instructions. Review read-only and keep two
axes separate:

- **Semantic accuracy:** establish what nodes, boundaries, and relationships mean.
  Check sequence, dependency, data flow, and state transitions; arrow direction
  and labels must carry a defined meaning. Look for omitted consequential branches,
  unproven relationships, and contradictions with nearby prose or source-evidenced
  facts when available and authorized. A plausible architecture is not evidence.
- **Communication:** choose a form suited to the question (flow, sequence, state,
  dependency). Check abstraction levels, unnecessary detail, ambiguous labels,
  grouping, reading direction, and whether a caption explains the takeaway.
  In actual renderings check legibility, crossings/clutter, and usefulness at
  typical documentation viewport sizes.

Inspect the rendered diagram with an existing renderer, browser, or screenshot
when available. Identify the artifact and viewport examined. If only text/Mermaid
source is accessible, assess semantics and likely complexity, explicitly stating
that visual rendering was not inspected. Do not infer layout, clipping, or successful
rendering from source. Do not add renderer dependencies just for this review.

Stop after the selected diagrams and consequential nearby contradictions. Return
material findings with location, reader consequence, evidence, semantic versus
visual status, confidence/limits, and minimal fixes: remove extraneous nodes, split
concerns, change diagram type, relabel an edge, clarify a legend, or correct a
contradicted relationship. Do not generate attractive but unsupported architecture,
rewrite files, or persist a report unless requested. Prompt constraints are not a sandbox.

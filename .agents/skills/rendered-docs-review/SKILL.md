---
name: rendered-docs-review
description: Inspect actual rendered documentation pages or screenshots for navigation, readability, responsive behavior, and accessible presentation when tools and access permit.
---

# Rendered documentation review

Read applicable instructions; establish permitted site/pages, reader task, and
available browser, local output, or screenshots. Use existing tools only. Do not
install Playwright, drivers, services, CI workflows, or cloud tools solely for this
review. Do not start builds/servers without applicable authorization; a review is
read-only by default and does not authorize configuration changes or publication.

If no rendering access exists, state that visual review could not be completed.
Request a small screenshot set (entry page with sidebar, representative deep page
with diagram/table, desktop and narrow widths), or explain how to open the existing
site preview. Continue only text-level observations and label them accordingly.
Markdown alone never establishes successful rendering.

With actual output, sample the entry page, a reader navigation path, and relevant
deep pages. Record URL/page, artifact/version if known, viewport, and interactions
actually tried. Check where observable:

- Discoverable navigation, sidebar density/hierarchy, current-page cues,
  breadcrumbs and next-page navigation where useful.
- Heading hierarchy; diagrams, tables, callouts, code, and mathematics that
  render, fit, and remain readable.
- Typography, line length, contrast, spacing, wrapping, overflow, and scroll burden;
  callouts/decorations should support the explanation.
- Desktop and narrow behavior only when both were examined.
- Accessibility basics: heading structure, meaningful link text, keyboard navigation,
  and contrast only where tools permit actual checks. Screenshots alone cannot
  establish keyboard behavior or a complete accessibility audit.

Use existing deterministic checks when appropriate and authorized, such as an
installed `mkdocs build --strict`, link checker, or accessibility tool. Builds may
write generated output: keep it in an allowed temporary location. Separate checks
executed and their results from suggestions; a successful build does not prove usability.

Stop at the bounded sample or access limit. Return only consequential findings
with precise page/element, evidence, reader/task effect, smallest useful fix, and
confidence/limits. Identify missing viewport or interaction checks. Leave pages,
source, tests, configuration, and instructions unchanged; do not save a report
unless requested. These behavioral boundaries are not enforced permissions.

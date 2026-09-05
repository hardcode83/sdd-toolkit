# Tasks: <feature name>

<!-- Markers, read by /sdd:run and the lifecycle gates (HTML comments, invisible
     when rendered). On a section heading: "hard" makes that section's
     implementer run on the stronger model; "panel: PASS <date>" is written by
     run itself when the section's review panel passes. On a task line:
     "manual" marks a task only a human can perform — run leaves it to you and
     it may travel with the PR as a deferred entry. -->

## 1. <section, e.g. Data layer>

- [ ] 1.1 <task — files touched — what done looks like> [R1]
- [ ] 1.2 ... [R1, R3]

## 2. <section>

- [ ] 2.1 ... [R2]

## N. Verification

<!-- Use the commands recorded in the consumer project's project.md; this
     template does not prescribe a language, framework, or test runner. -->
- [ ] N.1 Full test suite passes: `<exact command from project.md>`
- [ ] N.2 Lint/typecheck passes: `<exact command>`
- [ ] N.3 Manual check of the end-to-end flow: <how> <!-- manual -->

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

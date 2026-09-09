---
applies_to: ["<frontend-path>/**"]
---

# Frontend / design system

<!-- Set applies_to to this project's actual frontend root(s), e.g.
     "src/components/**" or "apps/web/**". Without a real applies_to this
     file never loads for the surfaces it should govern. -->

## Design system

<!-- Name the design system this project follows, if any, and where it is
     documented (a package, a Figma library, an internal doc). This
     project's own choices are the authority on aesthetics: do not adopt an
     external design language (Apple's Human Interface Guidelines, Material
     Design, or any other third-party system) as a substitute for the rules
     below. Mention one only if this project has deliberately adopted it. -->

## Design tokens

<!-- Where tokens live (color, spacing scale, typography scale, radii,
     elevation/shadow) and how a new value gets added versus reusing an
     existing one. A value that duplicates an existing token instead of
     reusing it is a violation of this section, not a style preference. -->

## Components

<!-- Where shared components live and how to check whether one already
     covers a need before adding another. Two components solving the same
     need side by side is a violation of this section. -->

## States

Interactive and data-bearing elements have an explicit representation for
each of the following, not just the default/happy path:

- **Loading** — visibly distinct from the loaded state while data is
  pending.
- **Empty** — visibly distinct representation when there is no data to
  show, not a blank area.
- **Error** — a user-facing representation of failure, not a silent no-op.
- **Disabled** — visibly distinct from the default state and not
  interactive.
- **Hover** — visibly distinct from the default state for pointer input.
- **Focus** — see Accessibility below.

<!-- Record this project's actual state-naming conventions, state-machine
     helpers, or component props that implement the above. -->

## Responsive

Layout declares verifiable breakpoints (media queries or equivalent
responsive utilities) instead of depending on a single fixed width.
Interactive elements and text stay usable — no unintended overflow or
clipping — at every width this project commits to supporting.

<!-- Record this project's actual supported breakpoints/widths and any
     device classes it targets explicitly. -->

## Accessibility

- **Contrast** — text-against-background pairs meet a documented minimum
  ratio (WCAG AA: 4.5:1 for normal text, 3:1 for large text, unless this
  project records a different objective threshold below).
- **Focus visible** — every interactive element has a focus state that is
  visibly distinguishable from its default and hover states; focus is
  never suppressed without an equivalent replacement.
- **Keyboard operability** — every interactive element is reachable and
  operable using only the keyboard, in a tab order that matches the
  visual/logical reading order.
- **Interaction target size** — touch/click targets meet a documented
  minimum size (WCAG 2.5.5 suggests 44x44 CSS pixels; record this
  project's actual minimum below if it differs).
- **Non-text content** — meaningful images and icon-only controls have an
  accessible name or alternative text.
- **Forms** — every field associates a programmatic label with its
  control.

<!-- Record this project's actual thresholds, tooling, and any documented
     exceptions to the baseline above. -->

## Testing

<!-- Describe what to verify for this component class, not which command
     runs it: that each declared state (loading, empty, error, disabled,
     hover, focus) renders as specified, that keyboard navigation reaches
     every interactive element in the expected order, that contrast and
     focus-visible hold for new color/component combinations, and that
     responsive breakpoints do not clip content. Point to where these
     checks live in this project without hardcoding how they are invoked. -->

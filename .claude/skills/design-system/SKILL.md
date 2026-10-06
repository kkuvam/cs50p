---
name: design-system
description: Extract a design system (tokens, components, patterns) from the existing Taildash/Tailwind UI into docs/design-system.md and reusable Jinja2 macros in app/templates/components/.
---
# Design system extraction

Inputs: screenshots, reference URLs, or existing templates named by the director.

1. Inventory what exists: `app/static/css/style.css` (pre-built Taildash on Tailwind v4, `@layer theme` CSS variables), `app/static/css/customizer.css`, `app/templates/layout.html`, the templates in `app/templates/*/`, `app/templates/components/`, `docs/design-system.md`. Update rather than replace.
2. Extract tokens from the `:root` variables and the classes templates actually use:
   - Color: brand, neutral scale, semantic (success/warning/danger/info), analysis status colors (PENDING/RUNNING/COMPLETED/FAILED/CANCELLED), surface and text colors, light/dark pairs.
   - Typography (Nunito), size scale, weights; spacing, radii, shadows, breakpoints.
   - Check text/background pairs meet WCAG 2.2 AA contrast (4.5:1 body, 3:1 large text and UI).
3. There is no Tailwind build: document only classes present in `style.css` (verify with `grep`). If a needed class is missing, propose a small addition to `customizer.css` instead of an arbitrary value.
4. Components as Jinja2 macros in `app/templates/components/`: button, input, select (incl. Select2), card, stat tile, table with sort/pagination, status badge, modal, flash/toast, empty state, loading state, log viewer. For each: variants, sizes, states (hover, focus-visible, disabled, loading, error).
5. Document in `docs/design-system.md`: token table, usage snippet per component, do/don't list.
6. Report: tokens documented, components added/changed, open questions.

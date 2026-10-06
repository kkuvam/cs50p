---
name: ui-review
description: Review new or changed Jinja2 templates and static JS/CSS for design-system compliance, accessibility (WCAG 2.2 AA), responsiveness, and loading/empty/error states.
---
# UI review

Scope: files in `app/templates/` and `app/static/` (excluding `vendors/`) changed in the current diff only.

Design system:
- Every class used exists in `app/static/css/style.css` or `customizer.css` (no build step: a missing class silently does nothing). Check with `grep`.
- Reuses macros from `app/templates/components/` and patterns in `docs/design-system.md` when they exist; extends `layout.html`.
- No inline styles or hard-coded colors unless documented.

Accessibility (WCAG 2.2 AA):
- Semantic elements (`button`, `a`, `nav`, `main`, `table`, `label`); no clickable `div`.
- Every input has a label; errors linked with `aria-describedby`; Select2/Tagify fields keep an accessible label.
- Visible `focus-visible` styles; logical tab order; target size >= 24x24px.
- Icon-only buttons have `aria-label`; charts have a text or table alternative; analysis status is not shown by color alone.
- Content updated by polling (run page status/log output) uses `aria-live` without stealing focus. Modals trap focus and close on Escape.

Responsive and states: works at 360px with no horizontal page scroll (wide tables and log output scroll inside their container); loading, empty, and error states exist (no analyses, missing report, failed run).

Safety: no `|safe` on user- or Exomiser-derived content; no patient data rendered for users who should not see it.

Report: verdict PASS or CHANGES REQUIRED, then `file:line - problem - fix`.

# Dashboard UI rules

This dashboard is for the publication's writer. Keep each screen focused on a question
the writer can answer or act on. Use the shared patterns below when adding a view.

## Visual system

`static/css/shell.css` owns the color, radius, and spacing tokens. Use its 4, 8, 12,
16, 24, and 32 pixel spacing steps. Panels use a 16 pixel radius; controls use 8
pixels. Pills and chart markers are the intentional shape exceptions. Green indicates
interactive selection; amber marks published posts and blue marks published Notes in
charts. Do not use those event colors as generic action colors.

Type uses the shared scale in `shell.css`: 37 pixel page headings, 20 pixel panel
headings, 14 pixel lead copy, 12 pixel controls and body text, and 10–11 pixel
supporting labels. The UI font is the system sans-serif; the serif is reserved for
the emphasized phrase in a page heading.

Use one page heading, a short explanation, then panels with a small eyebrow and a
descriptive heading. Supporting definitions belong in a footnote or disclosure near
the number they explain. Keep chart labels and units visible.

`static/css/comparison-map.css` owns the shared Posts and Notes dot-plot layout,
selection pane, tooltip, and compact cards. Keep each measure's scale and meaning in
its view-specific stylesheet. `static/js/comparison-elements.js` supplies the common
selection heading and metric tiles; use it when adding another comparison view.

## Controls

- `.refresh` is the outlined action style for refresh, export, and external-open
  actions. Use a text back link above a detail page; do not duplicate the back action
  inside its panel.
- `.segment` is the pressed-state style for changing the question or metric in place.
  Set `aria-pressed` and use the same behavior in every view.
- Table headers sort on click, expose `aria-sort`, and show the arrow. Text first
  sorts ascending; numeric measures first sort descending. Null values go last.
- Loading uses the shared spinner and a named status. Disabled controls have a
  disabled cursor; visible keyboard focus uses the shared focus ring.
- In a comparison map, the first selected dot reveals its details in the right pane.
  A second dot shows two compact cards there; **Clear selection** returns to the
  guidance. On narrow windows, the pane follows the plot. Selected dots do not show
  a duplicate hover tooltip.
- Export buttons say **Export CSV**. They export the rows matching the current
  filters, or the measured cohort on the Notes comparison page, regardless of table
  pagination. Explain any blank fields beside the table.

## Terms and scope

- **New subscribers** is the publication-period growth count and its Substack
  attribution. **Signups** is the conversion count on post and traffic-source views.
  Keep those labels distinct because their sources and time scopes differ.
- Posts have **views**; Notes have **impressions**. Do not put them on one scale or
  imply they count the same event.
- **Signup yield** means signups per 1,000 post views. The lifetime table requires
  1,000 views; the first-week portfolio map requires 100 first-week views and shows
  its own cohort medians. **Signup rate** means source-attributed signups divided by
  source users.
- The activity picker changes publication-period data and which Notes were published
  in the period. The Posts map uses seven complete days for each post, while the Posts
  table and individual Note totals are lifetime values. Mark that scope near each comparison.
- **Refresh publication** updates publication-period data. **Refresh post** and
  **Refresh Note** update their selected detail. Notes comparison loads its cohort
  automatically and can retry unavailable stats. Never present a Note's activity as
  proof that it caused a post spike or an individual subscriber conversion.

Use sentence case for action labels and capitalize **Note** when referring to the
Substack format. Cross-platform copy says **device**; name macOS or Windows only in
platform-specific instructions.

When adding a screen, compare it against Briefing, Posts, Discovery, Notes, and the
detail pages for wording, control states, spacing, empty/loading/error states, and
keyboard navigation. Run `python3 -m unittest tests.test_substack_dashboard` to
catch stylesheets or browser modules omitted from the local server's asset list.

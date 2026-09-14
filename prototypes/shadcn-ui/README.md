# DEIXIS — alternative shadcn UI

Independent, reversible UI prototype. Does not replace the repository's existing skill or planning documents.

## Run locally

```sh
npm ci
npm run dev
```

Open http://localhost:5178. Vite binds to 127.0.0.1 and uses strict port 5178.

```sh
npm run build
npm run lint
npm run preview -- --host 127.0.0.1 --port 5178 --strictPort
```

Stop the development server before previewing the build on the same port.

## Scope

React + TypeScript + Vite + Tailwind CSS. Actual shadcn components (Button, Tabs, Select, Sheet, Textarea), installed using the official CLI; generated components use Base UI. Fonts are bundled locally.

Interactive question intake with the earlier prototype's add-source menu, separate source/depth/model controls, four task shortcuts, and a home-screen resume list. PDF, BibTeX and RIS files can be selected for browser-only preview; research sessions retain filenames, not file contents. Library import and DOI lookup remain visibly unavailable until a persistent library and source connector exist. The model control links to the unverified Connections preview rather than implying a working model. The prototype also includes browser-local history and filtering, library, evidence panel, demo Markdown export, and persistent light/dark preference. Dark mode is the initial theme; the palette uses charcoal, warm ivory and a restrained metallic accent without green UI.

The earlier browser-only Quaestio concept was reimplemented inside this shadcn/React prototype as a clearly labelled synthetic sample workspace. It now demonstrates the separate Answer/Papers/Evidence table/Report views, fixed run-stage ledger, activity for actual UI actions, cell-specific source inspection and non-overwriting recheck, document-style report artifact, searchable/filterable library with session-only project corpus membership and browser PDF preview, connection status panels, and research-alert layout. The optional model-review demo remains separate. These are interface interactions, not implemented research services.

This is a UI preview: **no academic search, model invocation, PDF extraction or verified research findings**. Only question text, settings, and filenames persist in this browser's localStorage. No credentials are requested. Research view returns to the home screen on reload; saved questions can be reopened from history. Browser-local storage is not the planned application database or a backup. The sample library corpus, selected local PDFs, alert query, activity rows, and report-style choice are session-only and reset on reload.

## Verification

- TypeScript and production build; oxlint.
- Browser smoke: disabled empty submission, add-source/model menus, source-scope choices, task shortcuts, RIS file selection and local preview, sample collection routing, evidence panel open/close, saved history after reload.
- Visual checks at desktop viewport and 390px width; light theme. Dark theme entry and toggle exercised.

The research backend and source-grounded report generation remain outside this prototype.

## Optional model review prototype

Open a saved/new demo question, then select **Review with another model** from
Answer or Report. Choose a demo report/sample claim/sample candidate, a simulated
model and a review focus. Inspect the snapshot scope and optional additional-search
setting, then start the demo review. A separate sample report records the selected
model, focus, snapshot ID, timestamp and search option. Select findings to try
**Feed back** or **Request revision**; these stage demo feedback without changing
the main research text. Reopen the panel to return to that session's latest report.

All model names are fictional placeholders. Reports use the same illustrative
finding set for every input/model/focus; they are not generated analyses. No data
leaves the browser, no model or search runs, no source passage is verified, and no
revision executes. Review selections/reports/feedback exist in memory only and
reset on reload; only the latest review per session is retained. Production
immutable snapshots, review history, model discovery, persistence and actual
evidence-linked evaluation remain unimplemented.

Verification on 14 September 2026: build passed; lint completed with two existing
Fast Refresh export warnings in generated Button/Tabs components. Browser checks
covered both launch locations, model/focus/search selection, disabled feedback
before finding selection, both feedback actions, per-session separation/reopening,
focus return, Escape dismissal, light/dark appearance and a 390px mobile viewport.
These are UI checks, not research-method or model-performance validation.

## DEIXIS identity

The custom SVG source mark combines an open D with a diagonal reference line and a distinct source point. `public/deixis-icon.svg` is the transparent master; the UI applies the theme accent through a CSS mask. `public/favicon.svg` adds a warm paper background for browser tabs.

Legacy `quaestio-ui-*` browser-storage keys are retained to preserve existing prototype history and theme preferences.

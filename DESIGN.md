# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-06-23
- Primary product surfaces: Native Windows API request workspace, saved library, environments, scenarios, compare, converter, AI analysis, settings
- Evidence reviewed: `README.md`, `USER_MANUAL.md`, `screenshotv3.png`, `app.py`, `core.py`, `ui_scenario.py`, `ui_compare.py`, `ui_converter.py`, `ui_ollama_setup.py`, and `winui/CurlRunner.WinUI`

## Brand
- Personality: Practical, technical, quiet, and trustworthy
- Trust signals: Local-first data, explicit provider state, visible request status, redaction before AI calls, and deterministic reports
- Avoid: Marketing layouts, oversized headings, decorative gradients, nested cards, hidden destructive actions, and novelty animation

## Product goals
- Goals: Give developers and testers a fast native Windows client for composing, repeating, inspecting, comparing, and sequencing HTTP requests
- Goals: Preserve the working behavior and persisted data of the Python application during migration
- Non-goals: Replace full API collaboration platforms, implement cloud sync, or execute untrusted general-purpose scripts silently
- Success signals: Existing data opens without conversion, common request flows need few clicks, large text remains usable, and every migrated feature has a visible error/empty/loading state

## Personas and jobs
- Primary personas: Backend developers, QA engineers, automation testers, and support engineers
- User jobs: Reproduce API calls, debug failures, compare payloads, manage environments, rerun saved requests, and validate multi-step workflows
- Key contexts of use: Repeated desktop work, local/private APIs, CI preparation, incident investigation, and test evidence generation

## Information architecture
- Primary navigation: Requests, Library, Scenarios, Compare, Converter, AI, Settings
- Core routes/screens: Request workspace; history/collections; environment manager; scenario editor/runner; response analysis; utility tools
- Content hierarchy: Global environment and search in the title bar; route-level command bar; primary work surface; contextual status and results

## Design principles
- Principle 1: Optimize for scanning and repeated action, with dense tool layouts and stable control positions
- Principle 2: Show state at the point of action, including active environment, request progress, result status, AI provider readiness, and scenario progress
- Principle 3: Preserve raw data and make transformed views reversible or copyable
- Tradeoffs: Native parity is delivered incrementally; unsupported legacy behavior must be labeled rather than silently changed

## Visual language
- Color: Windows theme resources with one system accent plus semantic success, warning, and error states
- Typography: Segoe UI Variable for UI and Cascadia Code/Consolas for request and response content
- Spacing/layout rhythm: 4/8/12/16/20 px; compact command bars and tables; 20 px page padding
- Shape/radius/elevation: WinUI defaults, maximum 8 px card radius, minimal elevation
- Motion: Native control transitions only; no decorative motion
- Imagery/iconography: Fluent/WinUI symbols and icons; no custom illustration required for this operational tool

## Components
- Existing components to reuse: TitleBar, NavigationView, AutoSuggestBox, TabView, CommandBar, InfoBar, ListView, TextBox, NumberBox, ToggleSwitch, ContentDialog
- New/changed components: Request tabs, editable header rows, library split view, environment variable table, AI provider/status panel, scenario step editor and result details
- Variants and states: Empty, editing, running, cancelled, passed, failed, unavailable provider, and read-only result
- Token/component ownership: Shared colors and editor styles live in `App.xaml`; route-specific layouts remain in their page XAML

## Accessibility
- Target standard: WCAG 2.1 AA where applicable to Windows desktop UI
- Keyboard/focus behavior: Logical tab order, native focus visuals, Enter for primary actions where safe, Escape for dismiss/cancel, and Ctrl+F for search
- Contrast/readability: Theme resources and semantic InfoBar states; no status communicated by color alone
- Screen-reader semantics: Named controls, labels/headers for editable values, and text status summaries
- Reduced motion and sensory considerations: No essential animation and no flashing status

## Responsive behavior
- Supported breakpoints/devices: Windows desktop, minimum practical window width 960 px, x64
- Layout adaptations: NavigationView collapses automatically; dense two-pane layouts stack or scroll when width is constrained
- Touch/hover differences: All primary actions have visible labels or tooltips and usable native hit targets

## Interaction states
- Loading: Disable duplicate actions, show ProgressRing, preserve input
- Empty: Explain the missing object with one relevant creation/import action
- Error: Use InfoBar with actionable provider/request details
- Success: Show concise status, timing, size, or pass/fail summary
- Disabled: Keep unavailable controls visible when their prerequisite is understandable
- Offline/slow network: Support cancellation and explicit timeout; AI provider checks must not block navigation

## Content voice
- Tone: Direct, technical, concise
- Terminology: Use Request, Response, Environment, Collection, Scenario, Extractor, Assertion, and AI provider consistently
- Microcopy rules: State the problem and next action; do not expose raw secrets or internal exception dumps by default

## Implementation constraints
- Framework/styling system: C# WinUI 3 with Windows App SDK 2.1.3; WinUI Gallery is a control and layout reference, not a runtime dependency
- Design-token constraints: Prefer Windows theme resources and shared `App.xaml` styles
- Performance constraints: No hard character limit for stored/raw text; disable expensive formatting and cap highlighted matches for large content; perform network and diff work off the UI thread
- Compatibility constraints: Read and write `%USERPROFILE%/.curl_runner` JSON schemas used by the Python application
- Test/screenshot expectations: Release x64 build with zero warnings, unit coverage for parsers/rules/persistence, and desktop smoke checks for every navigation route

## Open questions
- [ ] Decide whether full Python pre-request scripts remain a compatibility bridge or are replaced by a constrained native script language / owner: product / impact: native packaging and security
- [ ] Decide whether OpenAI API keys may be persisted in Windows Credential Manager or remain session-only / owner: product-security / impact: convenience and secret handling
- [ ] Define a minimum supported Windows window size below 960 px / owner: design / impact: compact layout behavior

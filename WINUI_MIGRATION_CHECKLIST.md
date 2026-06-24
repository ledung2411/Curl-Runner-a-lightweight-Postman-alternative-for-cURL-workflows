# WinUI Feature Migration Checklist

Status legend: `[x]` complete, `[-]` partial, `[ ]` not migrated.

## Application Shell
- [x] Native WinUI 3 unpackaged x64 application
- [x] Mica, custom TitleBar, NavigationView, global search, theme switching
- [x] Persist theme and display preferences
- [x] Route global search results to tools, saved history requests, and scenarios

## Request Workspace
- [x] Method, URL, cURL, headers, body, SSL, redirects, timeout, repeat, send, cancel
- [x] Multiple request tabs with add, rename, close, and independent response state
- [x] Editable header rows with separate name and value fields
- [x] Environment substitution and missing-variable hint
- [-] Pre-request script editor and native execution log (general Python and `requests` calls remain a compatibility limitation)
- [x] Import request file, beautify body, clear request, and save to collection
- [x] Build cURL from request editor and keep both directions synchronized

## Response Workspace
- [x] Status, elapsed time, size, body, headers, info, and search
- [x] Script log and AI result tabs
- [x] Case-sensitive search and keyboard shortcut
- [x] Copy and Save raw response
- [-] JSON pretty view and full raw fallback work without data loss; color highlighting is disabled for WinUI runtime stability
- [x] Auto-detect UTF-8/UTF-16, honor declared code pages such as TIS-620, and use Windows-1252 fallback

## History and Collections
- [x] Persist sent requests to legacy `history.json`
- [x] Search, reopen, delete one, and clear history
- [x] Create, rename, and delete collections
- [x] Save, rename, open, and delete collection requests

## Environments
- [x] Load and save legacy `environments.json`
- [x] Select active environment globally
- [x] Create, rename, and delete environments
- [x] Add, edit, and delete key/value variables

## AI Analysis
- [x] Redact sensitive headers, query values, and body fields
- [x] Free Local provider through Ollama
- [x] Ollama install/server/model status and setup progress
- [x] Billing provider through OpenAI Responses API with session-only key dialog
- [x] Vietnamese analysis prompt and actionable provider errors

## API Scenarios
- [x] Load scenarios and execute groups sequentially with steps in parallel
- [x] Create, rename, delete, and save scenarios
- [x] Add, edit, duplicate, reorder, enable, and delete steps
- [x] Import open request tabs
- [x] Runtime environment substitution and cross-group extracted variables
- [x] JSON/header/regex extractors
- [x] Status/body/header/JSON assertions
- [x] Stop on fail, detailed log, and result summary
- [x] HTML, CSV, and JUnit XML reports with secret redaction

## Compare
- [x] Two-panel copyable line diff and multi-term search
- [x] Auto, cURL, JSON, text, and string normalization modes
- [x] Add/remove/rename multiple panels and load open request tabs
- [x] Background diff computation and batched UI rendering for large text

## Converter
- [x] JSON pretty/minify, escape/unescape, lines to array, swap, copy, clear
- [x] Load current response and switch long-line wrapping

## Settings and Packaging
- [x] Theme and Mica controls
- [x] Request defaults and AI defaults persisted
- [x] Document use of native Windows text scaling for font accessibility
- [x] Release x64 publish output and build documentation

## Completion Gate
- [x] Every incomplete item above is listed as a documented compatibility limitation
- [x] Legacy JSON data round-trips without destructive schema changes
- [x] Release build has zero warnings and all automated tests pass
- [x] Every route passes desktop visual and interaction smoke tests

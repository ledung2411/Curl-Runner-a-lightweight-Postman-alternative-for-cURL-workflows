# Curl Runner WinUI 3

This directory contains the native Windows migration of Curl Runner. The UI is
based on the controls and application structure demonstrated by the official
[WinUI Gallery](https://github.com/microsoft/WinUI-Gallery/tree/main). WinUI
Gallery is a reference application, not a UI package dependency.

The existing Python application remains the production implementation while
native feature parity is completed.

## Current Status

| Area | Native implementation | Status |
|---|---|---|
| App shell | Mica, TitleBar, NavigationView, global search, theme settings | Ready |
| Requests | Multiple tabs, cURL/builder sync, header rows, environments, scripts, repeat, history, response tools | Ready |
| Library | Legacy history and collection CRUD, search, reopen, save request | Ready |
| Environments | Legacy environment CRUD, variables, active selector, substitution hints | Ready |
| AI | Ollama status/setup/analyze and OpenAI billing provider with redaction | Ready |
| Scenarios | CRUD, sequential groups, parallel steps, extractors, assertions, logs and reports | Ready |
| Compare | Dynamic panels, Auto/cURL/JSON/text/string modes, background diff, incremental rendering and search | Ready |
| Converter | JSON pretty/minify, string escape/unescape, lines to JSON array | Ready |
| Settings | Persisted theme, Mica and request defaults | Ready |

See [`../WINUI_MIGRATION_CHECKLIST.md`](../WINUI_MIGRATION_CHECKLIST.md) for the
feature-by-feature migration status. The remaining compatibility gap is full
general-purpose Python pre-request scripting, including arbitrary Python module
imports and `requests` calls. The native runner supports `set_env`, `env`,
`env.get`, `log`, and timestamp expressions without requiring Python.

## Requirements

- Windows 10 version 2004 (build 19041) or newer
- .NET 10 SDK
- x64 Windows

Visual Studio is optional for command-line builds. For XAML designer support,
install Visual Studio with the Windows application development workload.

## Build

From the repository root:

```powershell
dotnet restore .\winui\CurlRunner.WinUI\CurlRunner.WinUI.csproj
dotnet build .\winui\CurlRunner.WinUI.sln -c Debug -p:Platform=x64
dotnet test .\winui\CurlRunner.WinUI.Tests\CurlRunner.WinUI.Tests.csproj -c Debug -p:Platform=x64
```

Run the unpackaged executable:

```powershell
.\winui\CurlRunner.WinUI\bin\x64\Debug\net10.0-windows10.0.22621.0\CurlRunner.WinUI.exe
```

The project uses Windows App SDK `2.1.3` and is self-contained, so the Windows
App Runtime does not need to be installed separately for this build.

Create the verified self-contained x64 artifact:

```powershell
powershell -ExecutionPolicy Bypass -File .\winui\build_artifact.ps1
```

The script creates `winui\artifacts\CurlRunner.WinUI-win-x64.zip`. Extract the
whole ZIP and run `CurlRunner.WinUI.exe`; do not copy the executable by itself,
because the adjacent .NET and Windows App SDK files are required.

This project currently packages the distributable from the direct self-contained
RID build. The `dotnet publish` stage is not used because it can regenerate an
invalid XAML binary with the current .NET 10 and Windows App SDK toolchain.

## Architecture

```text
CurlRunner.WinUI/
|-- Models/       Request, response, and scenario data
|-- Pages/        WinUI views and interaction handlers
|-- Services/     cURL parsing, HTTP execution, and legacy data loading
|-- App.xaml      Shared WinUI resources and editor styles
`-- MainWindow.*  Title bar, navigation, search, theme, and backdrop
```

History, collections, environments, scenarios, and WinUI settings are read from
and written to `%USERPROFILE%\.curl_runner` using the legacy JSON schemas.

## Accessibility

WinUI controls follow the Windows text scale configured under **Settings >
Accessibility > Text size**. Keyboard focus visuals and screen-reader names use
native control behavior; code editors keep a monospace font for alignment.

## Migration Rules

- Keep the Python application working while each feature is migrated.
- Reuse persisted data formats where practical.
- Match behavior before removing the corresponding Python screen.
- Validate every page on a real Windows desktop, not only with a successful
  compiler result.

# Baseline validation

Validated on Windows on 2026-11-08 using Python 3.15 and PySide6 6.12.0.

## Passed

- All 23 standard-library and offscreen Qt tests passed. Coverage includes protocol serialization/streaming, decisions, independent tabs, cancellation, prompts, attachments, themes, storage isolation, and Agentnik-scoped credential-store calls.
- Compile checks passed for `agentnik`, `tests`, and `tools`. Source launcher help passed.
- The light/dark wordmark and temporary-data welcome screenshots were visually inspected during baseline creation. The robot retains its geometry with red shading matching the wordmark; `agent` follows the theme and `nik` is warm red.
- `pip wheel . --no-deps --wheel-dir dist` built `agentnik-0.1.0-py3-none-any.whl`. The wheel installed into the local `.venv` without installing runtime dependencies again; existing PySide6/keyring dependencies are shared through system site packages.
- The installed package was imported with source-directory imports excluded. All seven packaged branding assets were present; SVG and PNG decoding passed.
- The installed application's entry point ran the offscreen event loop and exited successfully with temporary storage and mocked environment/endpoint discovery. Application/organization identity and the temporary history database were verified. The harness explicitly closed its database before deleting the temporary directory.
- Intended source files were audited for obsolete branding, private development endpoints, machine-specific paths, and common credential patterns. No matches were found. This is a targeted scan, not a guarantee against every possible secret format.
- The MIT license matches the supplied source verbatim, including Copyright (c) 2026 Nikolaus Spence. Project metadata identifies Nikolaus Spence as author.
- This repository was initialized independently, with no inherited history or remote at baseline creation. The user subsequently configured origin and published the baseline.

## Limits

No live inference or provider compatibility checks were run. Native interactive Windows use, macOS/Linux runtime behavior, frozen PyInstaller distributions, installers, and signing remain unverified. A Python wheel is not a frozen desktop distribution.

The default sandbox process setup still failed after the trust restart. Checks completed through the approved escalation path; Git commands used a repository-scoped ownership trust override without changing global Git settings.

## Milestone B managed research preview

- All 54 offline tests pass: the 23 baseline tests plus 29 research protocol, transport, credential, persistence, cancellation, and Qt checks, plus two edit/resend checks.
- Tests cover streamed/non-streamed native calls, multiple calls, argument assembly, thinking/identifiers in continuation, cross-turn citation provenance, aggregate/missing usage, malformed/unregistered calls, call/context/wire limits, time limits, cancellation and rejected late results, partial failed attempts, and narrow unsupported-tool classification.
- Transport mocks cover hostile IPv4/IPv6 URLs, mixed public/private DNS, pinned socket addresses with original TLS hostnames, redirect revalidation, credential isolation, content types, compression rejection, response/total byte caps, and readable text extraction. No real hostile destinations are contacted.
- The preview wheel builds and installs; source-directory imports were excluded when checking installed research modules, a mocked research turn, and an offscreen temporary-data Qt entry-point launch.
- Historical chat prompts expose an accessible pencil action. Offline tests verify text/image restoration without submission, draft replacement confirmation, persistence, running-request protection, and a mocked resend that appends a new turn while preserving prior history.
- Qt checks cover per-chat defaults, sources/links, credential-free exports, persisted research, interrupted reopen without execution, draft retention on cancellation, and rejection of late completions. Separate search credential-store calls and failed key replacement are tested with a fake keyring.
- Branding SVG loads are checked for Qt parser warnings. Eighteen empty paths were removed from each robot asset; regenerated PNG and ICO files remain byte-identical.
- Light/dark research screenshots were generated using temporary storage and explicitly simulated model/source responses, then visually inspected. They establish layout, not provider compatibility.

No live inference, search, or page-fetch requests were executed. Native interactive Windows checks, macOS/Linux, and frozen distributions remain unverified. Hosted search and tested routing/fallback are milestone C work; the preview is not a complete browsing release.

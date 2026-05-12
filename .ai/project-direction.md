# ofpm Project Direction

## Core Idea

`ofpm` is a personal offline package manager.

Its interface should feel familiar to users of `apt`, `yum`, or `dnf`, even when the implementation is specialized for offline bundle and patch workflows.

It is intended to manage:

- Linux offline install bundles
- WSL distro-specific installs
- Rocky/Red Hat-family targets
- Windows offline files and installers
- Conda/Anaconda payloads and environments
- compiler and binary toolchains
- large blobs such as Ollama models
- personal scripts, config, and development environment assets

The project should support both:

- full bundles
- patch/update bundles

## Design Principles

- content-addressed blob store by `sha256`
- target-aware management by profile and install root kind
- recorded target state used to decide applicability of full vs patch
- large blobs handled as complete new blobs rather than binary diff
- old or unknown states should be allowed to fall back to full bundle reinstall
- command and output conventions should stay as close as practical to mainstream package manager UX

## Online vs Offline Split

`ofpm` should clearly separate:

- target-side offline package management
- builder-side online artifact fetching

Target-side commands should assume no network.
Builder-side fetch commands may use network, but only to prepare artifacts for later offline installation.

The initial explicit fetch direction is:

- `ofpm fetch apt <package>`

The initial explicit transfer direction is:

- `ofpm export <bundle-name> --package ...`

This should generate either:

- a bundle directory
- or a bundle `tar.gz`

with a manifest that describes exactly what was exported.

Later expansions may include:

- `ofpm fetch dnf <package>`
- `ofpm fetch pip <package>`
- `ofpm fetch npm <package>`
- `ofpm fetch conda <package>`

## UX Guidance

- Prefer familiar package manager verbs and flows.
- The user should be able to learn package-manager concepts by using `ofpm`.
- Use `yum`/`dnf` as the main CLI model, while borrowing selective `apt` wording when it is clearer.
- Good examples for future command shape:
  - `ofpm list`
  - `ofpm show <package>`
  - `ofpm install <package>`
  - `ofpm upgrade <package>`
  - `ofpm verify <package>`
  - `ofpm state`
- Because this project is offline-focused, commands should also surface bundle, patch, profile, and verification details that normal online package managers often hide.

## Managed Root Policy

Use managed roots instead of scattering owned files across arbitrary locations.

- system root: `/opt/ofpm`
- user root: `$HOME/.ofpm`

Inside those roots, keep package-owned content isolated from unrelated user or system files.

Phase 1 does not require automatic PATH integration.
Running tools from inside the managed root is acceptable.
When desired, `ofpm` should be able to print shell configuration that makes managed tools win in PATH order.

## Runtime Assumption

Phase 1 assumes `python3` is already available on Linux/WSL targets.

This is a manager-level prerequisite, not necessarily a payload-level prerequisite.

- `ofpm` manager depends on Python
- managed packages may or may not depend on Python themselves

Support for no-Python targets is deferred.

## Package Separation Guidance

Recommended early package split:

- `ollama-runtime`
- `ollama-model-gemma4-e4b`
- `node-runtime`
- `pi-app`
- `personal-config`

Why separate runtime and model:

- version cadence differs
- model blobs are very large
- patching strategy differs
- verification strategy differs

## Verification Guidance

Offline restore must not be judged only by superficial listing commands.

For Ollama-style assets, eventual verification should include:

- manifest-to-blob closure checks
- blob integrity checks
- metadata/show checks
- real execution checks where feasible

Restore success and runtime resource success must be tracked separately.

Example:

- manifest/blob closure restored correctly
- runtime still fails because target memory is insufficient

Those are different problem classes and should not be collapsed into one status.

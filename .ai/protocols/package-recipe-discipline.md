# Package Recipe Discipline

## Purpose

Keep package meaning and package-specific behavior inside the package definition boundary.

## Rules

- Each installable package should be defined by a package-local `package.py`.
- The package definition is the first place to look for package identity, version, target, env,
  dependencies, integrations, and payload declarations.
- Generic behavior should be metadata-first.
- Package-local methods should exist only when the package needs behavior beyond generic metadata
  handling.
- Avoid spreading one package's meaning across generic runtime files.

## Structure

Preferred shape:

- one `Recipe` class per package file
- one `RECIPE = Recipe()` export per package file

## Ownership

Keep these package-local when they are package-specific:

- default config content
- package-specific verify logic
- package-specific install side effects
- package-specific remove cleanup

Do not move package meaning into shared helper files unless the behavior is truly reusable across
multiple packages.

## Simplicity Rule

If a package can be expressed with shared metadata-driven install/remove/verify, do that first.
Do not add a package-local override just because it feels more explicit.

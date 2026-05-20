# Repo Import And Provider Policy

## Builder-Side Rule

Builder-side commands prepare repo content. They do not act like target-side package management.

## Source Import Rules

- `repo import` takes a direct local builder-side input path
- `repo import` turns that path into a repo package
- imported native packages should land under `repos/<name>/ofpm/<package>/<version>/`
- imported package definitions should be valid package-local recipes

## Provider Rules

- provider acquisition belongs in provider-specific code such as `ofpm/apt.py`
- provider snapshots should land under `repos/<name>/<provider>/<package>/<version>/`
- provider snapshot metadata should remain distinct from installed-state truth

## Normalization Rule

When builder-side input is converted into repo content, the CLI should own layout details.
Users should not need to hand-build repo internals.

## Target-Side Rule

Target-side commands should consume repo snapshots and managed-root state only.
They must not fetch from network sources.

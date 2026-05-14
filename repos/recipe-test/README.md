# repos/recipe-test

Lightweight `package.py + payload/` sandbox repo used to validate the next repo layout.

Each package version lives in one directory:

- `package.py`: package metadata and optional future hooks
- `payload/`: actual installable content

This repo intentionally keeps target information inside each package definition instead of
separate `catalog/`, `profiles/`, or `schemas/` trees.

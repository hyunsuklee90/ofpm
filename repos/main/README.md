# repos/main

Portable self-contained `ofpm` repo snapshot.

Contents:

- `catalog/packages/`
- `catalog/providers/apt/`
- `artifacts/ofpm/`
- `artifacts/providers/apt/`
- `profiles/`
- `schemas/`

Typical target-side registration flow:

```bash
ofpm repo add main /opt/ofpm/repos/main --scope user
```

Then inspect and use the repo:

```bash
ofpm list --all
ofpm show node-runtime
ofpm apt list --downloaded
```

For package-specific shell setup, use:

```bash
ofpm env package pi-agent --root user
ofpm env package pi-agent --root user --format modulefile
```

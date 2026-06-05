# repos/ofpm/main

Portable native `ofpm` package repo snapshot.

Contents:

- `<package>/<version>/package.py`
- `<package>/<version>/payload/`

Typical target-side registration flow:

```bash
ofpm repo add main /opt/ofpm/repos/ofpm/main
```

Then inspect and use the repo:

```bash
ofpm list --all
ofpm show node
```

For package-specific shell setup, use:

```bash
ofpm env package pi-agent --root user
ofpm env package pi-agent --root user --format modulefile
```

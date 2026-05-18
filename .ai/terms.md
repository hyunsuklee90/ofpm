# ofpm Terms

Use these terms consistently across docs, code review, and future refactors.

## Repo Terms

### repo snapshot

The portable directory tree copied from one machine to another for offline use.

Rule:

- prefer `repo snapshot` over `bundle`

### provider snapshot

A downloaded payload and metadata set from an external provider such as `apt`.

Rule:

- use this term for upstream-acquired content before or while it is represented inside a repo

## Package Terms

### package recipe

The package-local Python definition that owns package metadata and package-specific behavior.

Examples:

- `repos/main/ofpm/node-runtime/24.13.1/package.py`
- `repos/main/apt/zstd/<version>/package.py`

### payload

The actual installable or provider-owned content associated with a package definition.

Examples:

- `bin/`, `lib/`, `share/` file trees
- upstream archives
- model blobs and manifests
- downloaded `.deb` files

Rule:

- `package.py` is the description and behavior
- `payload/` is the package content

## State Terms

### installed state

The current tool-owned JSON record describing an installed package instance.

### receipt

The uninstall-oriented install record used to remove files conservatively.

### ownership

The state used to decide whether shared files or shared dependencies may be removed safely.

## Dependency Terms

### dependency

A required package relationship.

Rule:

- `depends` contains only required relationships
- if a listed dependency is missing or version-incompatible, install/verify should fail

### integration

A non-required relationship that enables additional behavior when another package is present.

Examples:

- `pi-agent` integrating with `ollama-runtime`
- an installed model becoming available to a local runtime when both exist

Rule:

- `integrations` are not install blockers
- do not encode optional relationships as `depends` with `required=False`

## Execution Terms

### builder-side

Commands or code paths that may acquire or normalize content before offline use.

### target-side

Commands or code paths that act on a registered repo and managed roots without network access.

# Install Verify Remove Discipline

## Generic-First Rule

Basic file copy, basic removal, and basic file verification should be handled by shared generic
code when metadata is sufficient.

## Package-Local Override Rule

Use package-local `install`, `verify`, or `remove` only when the package needs extra behavior such
as:

- archive extraction with package-specific structure
- offline package-manager subprocess flow
- package-owned config regeneration
- package-owned integration side effects
- runtime checks that cannot be expressed as generic file verification

## Separation Rules

- Shared runtime support owns reusable mechanics.
- Package recipes own package meaning.
- CLI owns orchestration and output, not lifecycle semantics.

## Remove Rules

- removal must be receipt-driven
- ambiguous deletion must stay conservative
- package-specific cleanup belongs in the package recipe if it depends on package meaning

## Verify Rules

- `list` is not verification
- generic verification should check declared files and installed state coherence
- package-specific verification may add executable checks or config checks
- verification should report what was checked and what failed

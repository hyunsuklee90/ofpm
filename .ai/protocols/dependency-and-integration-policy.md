# Dependency And Integration Policy

## Core Rule

- `depends` means required package relationships only.
- `integrations` means optional relationships only.

## Dependency Rules

- If a relationship is required for install or verify to succeed, it belongs in `depends`.
- Missing or version-incompatible `depends` entries must fail install or verify.
- Do not encode optional relationships as `depends` with `required=False`.
- Prefer versioned dependencies when the relationship is version-sensitive.

## Integration Rules

- If another package only enables extra features, it belongs in `integrations`.
- Missing `integrations` entries must not block install.
- `integrations` may still carry version information and a reason string.

## Examples

Good:

- `pi-agent` depends on `node-runtime`
- `pi-agent` integrates with `ollama-runtime`
- `ollama-model-*` integrates with `ollama-runtime`

Bad:

- optional runtime support expressed as `depends` with `required=False`

## Output Rule

CLI output should present `dependencies` and `integrations` as separate sections.

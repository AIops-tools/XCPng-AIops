# Release notes — xcpng-aiops 0.2.1

Previous release: 0.2.0.

## Findings now carry an explicit rank

`vm_health_rca` and `sr_usage_rca` already ordered their findings worst-first by
severity; each finding now also carries an explicit 1-based `rank`, so priority is
stated in the payload rather than left implicit in list position. A consumer —
notably a smaller local model summarising the result — should never have to infer
urgency from position.

Additive: no existing field changed meaning.

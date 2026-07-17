# Changelog

## v0.1.0 — 2026-07-17

Initial preview release: governed XCP-ng operations via Xen Orchestra's REST
API (`/rest/v0`) with a fully bundled governance harness. **Mock-validated
only — not yet verified against a live Xen Orchestra instance.**

### Highlights

- **27 MCP tools** (19 read, 8 write), every one wrapped with the bundled
  `@governed_tool` harness (audit / policy / budget / undo / risk tiers).
- **Four flagship RCA analyses** with structured cause + action findings:
  - `vm_health_rca` — halted-unexpectedly / paused VMs, guest tools missing,
    CPU & memory pressure from RRD stats.
  - `sr_usage_rca` — SRs ranked near-full/critical, thin-provision overcommit,
    orphaned VDIs with reclaimable bytes.
  - `backup_failure_rca` — failed/skipped runs classified (vdi-chain, quiesce,
    transport, storage-full).
  - `pool_patch_ha_posture` — missing patches, pending reboots, version skew,
    HA state per pool.
- **Governed writes** with dry-run previews and honest reversibility:
  `vm_start` ↔ `vm_stop` undo pairs; `vm_migrate` records migrating back to
  the captured source host; `snapshot_create` records deleting the REAL
  snapshot id returned by XO; `snapshot_delete` / `snapshot_revert` are
  high-risk, capture prior state, and declare no undo; `sr_rescan` is a
  low-risk metadata refresh.
- **Encrypted secret store** — the XO personal authentication token is stored
  encrypted in `~/.xcpng-aiops/secrets.enc` (Fernet + scrypt master password);
  never plaintext on disk. `xcpng-aiops init` onboarding wizard + `secret`
  command group; `XCPNG_AIOPS_MASTER_PASSWORD` for non-interactive/MCP use.
- **Token-in-header auth** against XO: both `Authorization: Bearer` and the
  `authenticationToken` cookie are sent for compatibility across XO 5.x.
- **Secure by default** — with no rules.yaml, high-risk writes are denied
  unless `XCPNG_AUDIT_APPROVED_BY` names an approver; `init` seeds a starter
  rules.yaml with the dual-control tier.
- **Doctor** — config + encrypted-store checks, XO reachability, token
  validity, and managed-pool count per target.

### Scope notes

- Requires a Xen Orchestra instance (5.x, `/rest/v0`); per-host XAPI access is
  out of scope for v0.1.
- Endpoint paths are modelled against the documented XO REST API and are
  mock-validated only — verify against a live XO before trusting writes.

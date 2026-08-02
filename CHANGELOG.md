# Changelog

## v0.5.0 — 2026-08-02

### Changed (BREAKING)
- **Requires MCP SDK 2.0** (`mcp[cli]>=2.0,<3.0`). `mcp.server.fastmcp` no longer exists in 2.0; the server is now built with `MCPServer` and reports its package version in the stdio handshake.

### Fixed
- **`undo apply` works from the CLI.** Every write tool is imported lazily inside its own CLI command, so a CLI-driven undo ran in a process where the inverse tool was never registered and failed with "inverse tool is not registered" — for every write tool. Only the MCP entry point, which imports the whole server, worked. Found while live-verifying against a real cluster.
- **An undetermined outcome is audited `unknown`, not `ok`.** The harness only classified a result as undetermined when the payload *also* carried an `error` key, so a write that looked successful but had not been confirmed was recorded as a success.
- **Every call failed against a real Xen Orchestra.** The client sent both `Authorization: Bearer` and the `authenticationToken` cookie; current XO rejects a request carrying two auth methods with `400 Having multiple authentication methods is not supported`. Only the cookie is sent now (Bearer alone is 401, both are 400). Live-verified against XCP-ng 8.3 + XO.
- **`sr rescan` 404'd**: XO names the action `scan`. Confirmed against XO's own OpenAPI spec.
- **Snapshot revert 404'd**: revert is a VM-level action, `POST /vms/{vm}/actions/revert_snapshot` with the snapshot id in the body — `/vm-snapshots/{id}/actions/revert` does not exist.
- A halted VM reported a `host` that is not a host. XO overloads `$container` as the resident host while running and the **pool** id when halted; `host` is now null when the VM is not resident on one.


## v0.4.0 — 2026-07-21

### Changed (BREAKING)
- **Removed the authorization layer** — read-only mode, the approver gate, and rules.yaml deny are gone. The skill no longer decides read vs write; that is the agent's judgement or the connecting account's permissions. `<PREFIX>_READ_ONLY` now has no effect (a startup warning is logged); `<PREFIX>_AUDIT_APPROVED_BY`/`_RATIONALE` are optional audit annotations.
- The retained guarantee is **unbypassable audit over MCP and CLI alike** — no unaudited entry point. Harness = audit + runaway safety guard + undo + sanitize; `risk_level` is a descriptive audit label, not a gate.

See RELEASE_NOTES.md for tool-specific changes.


## v0.3.0 — 2026-07-20

### Fixed
- **`vm_stop` refuses the Xen Orchestra VM when you declare it.** XO is commonly a VM on the pool it manages, and stopping it kills the request in flight; recovery needs console access.
- **CLI writes now exit non-zero on a governed error.** Eight commands previously discarded the governed result and printed success — a policy denial, an unreachable XO, or a refused self-target all reported as done..
- Harness: a write whose response is lost is audited `status=unknown`, not `error` — it may have taken effect. Undo tokens gain `effectVerified` (undo.db migrated in place).
- Harness: a dry-run no longer records an undo token, and no longer requires a named approver. Guards now run on the preview path.
- Truncated strings end in an ellipsis instead of being cut silently; error messages are capped at 800 chars, not 300.

See RELEASE_NOTES.md for the full detail.

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

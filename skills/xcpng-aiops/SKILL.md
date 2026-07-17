---
name: xcpng-aiops
description: >
  Use this skill whenever the user needs to operate an XCP-ng virtualization fleet through Xen Orchestra — a one-shot fleet health overview; VMs (list/get/RRD stats), hosts, pools, storage repositories (SRs) and VDIs, VM snapshots, backup jobs and run logs, XO tasks; four RCA analyses (VM health, SR usage, backup-job failures, pool patch & HA posture); and governed writes (VM start/stop/reboot/migrate, snapshot create/delete/revert, SR rescan).
  Always use this skill for "xcp-ng vm", "xen orchestra", "xo backup failed", "sr full", "orphaned vdi", "xcp-ng snapshot", "migrate vm to another host", "xcp-ng patches", or "pool HA" when the context is explicitly XCP-ng / Xen Orchestra / a Xen-based fleet.
  Do NOT use when the target is not an XCP-ng fleet managed by Xen Orchestra — other hypervisors (Do NOT use for Proxmox VE — use proxmox-aiops), NAS/storage appliances, backup software suites, container clusters, and network devices are out of scope (negative routing hints only).
  Preview — common XCP-ng-via-XO operations with a built-in governance harness (audit, policy, token budget, undo, risk-tiers). Mock-validated only, not yet verified against a live Xen Orchestra instance.
installer:
  kind: uv
  package: xcpng-aiops
argument-hint: "[vm/sr/snapshot uuid or describe your XCP-ng task]"
allowed-tools:
  - Bash
metadata: {"openclaw":{"requires":{"env":["XCPNG_AIOPS_CONFIG"],"bins":["xcpng-aiops"],"config":["~/.xcpng-aiops/config.yaml","~/.xcpng-aiops/secrets.enc"]},"optional":{"env":["XCPNG_AIOPS_MASTER_PASSWORD"]},"primaryEnv":"XCPNG_AIOPS_CONFIG","homepage":"https://github.com/AIops-tools/XCPng-AIops","emoji":"🖥️","os":["macos","linux"]}}
compatibility: >
  Standalone, self-governed XCP-ng operations via Xen Orchestra's REST API /rest/v0 (preview). REQUIRES a Xen Orchestra instance (XO from sources or the Xen Orchestra Appliance, 5.x) — XO is the management plane; direct per-host XAPI access is out of scope for v0.1. The governance harness (audit, policy, token/runaway budget, undo, risk-tiers) is bundled in the package — no external skill-family dependency.
  All write operations are audited to a local SQLite DB under ~/.xcpng-aiops/ (relocatable via XCPNG_AIOPS_HOME).
  Credentials: Each XO target's personal authentication token is stored ENCRYPTED in ~/.xcpng-aiops/secrets.enc (Fernet/AES-128 + scrypt-derived key) — never plaintext on disk. Run 'xcpng-aiops init' to onboard, or 'xcpng-aiops secret set <target>' to add one (create the token in the XO UI: user menu → Personal tokens, or `xo-cli --createToken`). The store is unlocked by a master password from XCPNG_AIOPS_MASTER_PASSWORD (non-interactive/MCP/CI) or an interactive prompt (CLI on a TTY). A legacy plaintext env var XCPNG_<TARGET_NAME_UPPER>_TOKEN is still honoured as a fallback with a deprecation warning (migrate with 'xcpng-aiops secret migrate'). The token is sent in headers (Authorization: Bearer + authenticationToken cookie) at request time and held only in memory; tokens are never logged or echoed.
  Destructive operations (snapshot delete/revert, vm stop/reboot/migrate) require double confirmation at the CLI layer and support --dry-run; every write MCP tool takes a dry_run preview (no API call, no undo recorded). All write tools pass through the @governed_tool decorator (pre-check + budget guard + audit + risk-tier gate). vm_start↔vm_stop record each other as inverses; vm_migrate records migrating back to the captured source host; snapshot_create records deleting the REAL snapshot id XO returned; snapshot_delete and snapshot_revert are high-risk and irreversible (capture BEFORE state, record no undo).
  Webhooks: none — no outbound network calls beyond the configured Xen Orchestra REST API endpoint.
  SSL: verify_ssl defaults to true; disable only for self-signed lab certificates.
  Transitive dependencies: httpx (HTTP client) and the MCP SDK. No post-install scripts or background services.
  PREVIEW: mock-validated only; endpoint paths modelled against the documented Xen Orchestra REST /rest/v0 API need live verification.
---

# XCP-ng AIops (preview)

> **Disclaimer**: This is a community-maintained open-source project and is **not affiliated with, endorsed by, or sponsored by Vates, the XCP-ng project, or the Xen Orchestra project.** "XCP-ng", "Xen Orchestra", and "Xen" are trademarks of their owners. Source code is publicly auditable at [github.com/AIops-tools/XCPng-AIops](https://github.com/AIops-tools/XCPng-AIops) under the MIT license.

Governed XCP-ng operations via **Xen Orchestra's REST API** — **27 MCP tools**, every one wrapped with the bundled `@governed_tool` harness: a local unified audit log under `~/.xcpng-aiops/`, policy engine, token/runaway budget guard, undo-token recording, and graduated-autonomy risk tiers. The XO authentication token is stored **encrypted** (`~/.xcpng-aiops/secrets.enc`, Fernet + scrypt) — never plaintext on disk.

> **Requires a Xen Orchestra instance** (5.x with `/rest/v0`) — XO is the management plane; per-host XAPI is out of scope for v0.1. **Standalone**: the governance harness is bundled in the package (`xcpng_aiops.governance`) — xcpng-aiops has no external skill-family dependency. **Preview / mock-only**: common operations, not yet exhaustive, not yet validated against a live XO.

## What This Skill Does

| Category | Tools | Count | Read or Write |
|----------|-------|:-----:|:-------------:|
| **Overview** | fleet health overview | 1 | 1 read |
| **VMs** | list, get, RRD stats, health RCA | 4 | 4 read |
| | start, stop, reboot, migrate | 4 | 4 write (medium) |
| **Hosts** | list, get | 2 | 2 read |
| **Pools** | list, get, patch & HA posture RCA | 3 | 3 read |
| **SRs / VDIs** | list, get, VDI list (orphan filter), usage RCA | 4 | 4 read |
| | rescan | 1 | 1 write (low) |
| **Snapshots** | list | 1 | 1 read |
| | create (medium), delete (high), revert (high) | 3 | 3 write |
| **Backups** | jobs, run logs, failure RCA | 3 | 3 read |
| **Tasks** | list | 1 | 1 read |

## Quick Install

```bash
uv tool install xcpng-aiops
xcpng-aiops init       # interactive wizard: XO URL + encrypted token
xcpng-aiops doctor     # XO reachability + token validity + pool count
```

## When to Use This Skill

- Triage an XCP-ng fleet (`overview`): pools, hosts, VMs by state, SRs near full, recent backup failures
- Root-cause an unhealthy VM (`vm health-rca`): halted unexpectedly, paused, guest tools missing, CPU/memory pressure
- Root-cause storage pressure (`sr usage-rca`): SRs ranked near-full, thin-provision overcommit, orphaned VDIs with reclaimable bytes
- Root-cause backup failures (`backup failure-rca`): vdi-chain / quiesce / transport / storage-full classification
- Check patch & HA posture (`pool posture`): missing patches, pending reboots, version skew, HA state
- Snapshot a VM before a risky change; start/stop/reboot/migrate VMs under governance

**Do NOT use when** the target is not an XCP-ng fleet managed by Xen Orchestra — other hypervisors (Do NOT use for Proxmox VE — use proxmox-aiops), NAS/storage appliances, backup software suites, Kubernetes/containers, and network devices are out of scope for this skill.

## Related Skills — Skill Routing

| If the user wants… | Use |
|--------------------|-----|
| XCP-ng VMs / hosts / pools / SRs / snapshots / XO backups | **xcpng-aiops** (this skill) |
| Proxmox VE operations | **proxmox-aiops** |
| NAS/storage appliance operations | a storage-appliance ops skill |
| Backup-software suite job/restore operations | a backup-software ops skill |
| Container/cluster lifecycle | a cluster ops skill |

## Common Workflows

### Snapshot a VM before a change, then roll back if needed

1. `xcpng-aiops vm list` → confirm the VM uuid
2. `xcpng-aiops snapshot create <vm-uuid> pre-change` → XO returns the new snapshot's id; an inverse `snapshot_delete` for THAT id is recorded
3. Make your change; if it went wrong: `xcpng-aiops snapshot revert <snapshot-uuid>` (double confirm — replaces current state, IRREVERSIBLE)
4. When done: `xcpng-aiops snapshot delete <snapshot-uuid> --dry-run` → preview; then without `--dry-run` (double confirm — IRREVERSIBLE, captures BEFORE state, no undo)

### Backup job failing every night

1. `xcpng-aiops backup failure-rca` → failures grouped by job, classified: vdi-chain / quiesce / transport / storage-full
2. vdi-chain? Let the coalesce finish, then `xcpng-aiops sr rescan <sr-uuid>`; avoid stacking snapshots
3. transport? Test the backup remote in the XO UI (Settings → Remotes)
4. `xcpng-aiops backup logs -n 20` → confirm the next run went green

### Evacuate a host for maintenance

1. `xcpng-aiops pool posture` → check patch/reboot state and version skew first
2. `xcpng-aiops vm list --state Running` → VMs on the host
3. `xcpng-aiops vm migrate <vm-uuid> <dest-host-uuid>` per VM (double confirm; undo = migrate back to the captured source host)

## Usage Mode

| Scenario | Recommended | Why |
|----------|:-----------:|-----|
| Local/small models | **CLI** | fewer tokens than MCP |
| Cloud models (Claude, GPT) | Either | MCP gives structured JSON I/O |
| Automated pipelines | **MCP** | type-safe parameters, audited |

## MCP Tools (27 — 19 read, 8 write)

| Category | Tools | R/W |
|----------|-------|:---:|
| Overview | `overview` | Read |
| VMs | `vm_list`, `vm_get`, `vm_stats`, `vm_health_rca` | Read |
| | `vm_start`, `vm_stop`, `vm_reboot`, `vm_migrate` | Write |
| Hosts | `host_list`, `host_get` | Read |
| Pools | `pool_list`, `pool_get`, `pool_patch_ha_posture` | Read |
| SRs / VDIs | `sr_list`, `sr_get`, `vdi_list`, `sr_usage_rca` | Read |
| | `sr_rescan` | Write |
| Snapshots | `snapshot_list` | Read |
| | `snapshot_create`, `snapshot_delete`, `snapshot_revert` | Write |
| Backups | `backup_job_list`, `backup_log_list`, `backup_failure_rca` | Read |
| Tasks | `task_list` | Read |

**Harness features that light up**: `vm_start`↔`vm_stop` record each other as inverses (with `_undo_id`); `vm_migrate` captures the REAL source host BEFORE moving and records "migrate back"; `snapshot_create` captures the REAL snapshot id from the XO response and records "delete THAT snapshot". `snapshot_delete` and `snapshot_revert` are `risk_level=high`, capture BEFORE state, and declare no undo (irreversible). Every write takes `dry_run=True` (no API call, no undo). All 27 tools are audit-logged under `~/.xcpng-aiops/` and pass through the policy pre-check + budget/runaway guard + graduated risk-tier gate. Start any triage with `overview`.

## CLI Quick Reference

```bash
xcpng-aiops init                                    # onboarding wizard (encrypted XO token)
xcpng-aiops overview [--target <t>]                 # fleet health summary
xcpng-aiops vm list [--state Running] [--pool <uuid>]
xcpng-aiops vm get <vm_uuid>
xcpng-aiops vm stats <vm_uuid> [-g minutes]
xcpng-aiops vm health-rca [<vm_uuid>]               # RCA: cause + action
xcpng-aiops vm start <vm_uuid> [--dry-run]
xcpng-aiops vm stop <vm_uuid> [--force] [--dry-run]      # double confirm
xcpng-aiops vm reboot <vm_uuid> [--force] [--dry-run]    # double confirm
xcpng-aiops vm migrate <vm_uuid> <host_uuid> [--dry-run] # double confirm
xcpng-aiops host list / get <host_uuid> / missing-patches <host_uuid>
xcpng-aiops pool list / get <pool_uuid>
xcpng-aiops pool posture [<pool_uuid>]              # RCA: patches / reboots / skew / HA
xcpng-aiops sr list / get <sr_uuid>
xcpng-aiops sr vdis [--sr <uuid>] [--orphaned-only]
xcpng-aiops sr usage-rca                            # RCA: near-full / overcommit / orphans
xcpng-aiops sr rescan <sr_uuid> [--dry-run]
xcpng-aiops snapshot list [--vm <uuid>]
xcpng-aiops snapshot create <vm_uuid> <name> [--dry-run]
xcpng-aiops snapshot delete <snapshot_uuid> [--dry-run]   # double confirm, IRREVERSIBLE
xcpng-aiops snapshot revert <snapshot_uuid> [--dry-run]   # double confirm, IRREVERSIBLE
xcpng-aiops backup jobs / logs [-n 50]
xcpng-aiops backup failure-rca [-n 50]              # RCA: vdi-chain / quiesce / transport
xcpng-aiops task list [--status failure]
xcpng-aiops secret set <target> / list / rm <target> / migrate / rotate-password
xcpng-aiops doctor                                  # XO reachability + token + pool count
xcpng-aiops mcp                                     # start MCP server (stdio)
```

See `references/cli-reference.md` for the full command list.

## Troubleshooting

### "Config file not found"
Run `xcpng-aiops init` to set up your first target (writes `~/.xcpng-aiops/config.yaml` and stores the XO token encrypted).

### "No XO authentication token for target '<name>'"
Add it to the encrypted store: `xcpng-aiops secret set <name>` (prompts hidden), or run `xcpng-aiops init`. Create the token in the XO UI (user menu → Personal tokens) or with `xo-cli --createToken`. For non-interactive use (MCP/CI), also export `XCPNG_AIOPS_MASTER_PASSWORD` so the store can be unlocked without a prompt.

### "Master password not set" / "Wrong master password"
The encrypted store `~/.xcpng-aiops/secrets.enc` is unlocked by `XCPNG_AIOPS_MASTER_PASSWORD` (or an interactive prompt). If you forgot it, delete `secrets.enc` and re-run `xcpng-aiops init`. Rotate it with `xcpng-aiops secret rotate-password`.

### "Authentication/authorization failed (401/403)"
The XO token is wrong, expired, or revoked, or the XO account lacks permission. Regenerate the token in the XO UI (user menu → Personal tokens) and update it: `xcpng-aiops secret set <name>`.

### "Could not reach Xen Orchestra … check the XO URL"
Confirm the XO web UI is reachable at the configured `url` and that `api_path` is `/rest/v0` (XO 5.x). For self-signed certificates set `verify_ssl: false` on the target (lab only).

### "Resource not found (404)"
The VM/SR/snapshot uuid is stale, or this XO release lacks the endpoint. List the parent collection first (`vm list`, `sr list`, `snapshot list`) to get a current uuid.

### Doctor says "manages no pools yet"
Your XO instance is reachable but has no XCP-ng servers connected — add them in the XO UI (Settings → Servers).

## Audit & Safety

All operations are automatically audited via the bundled `@governed_tool` decorator (`xcpng_aiops.governance`):
- XO token stored **encrypted** in `~/.xcpng-aiops/secrets.enc` (Fernet/AES-128 + scrypt key derivation; chmod 600) — never plaintext on disk; the master password is never stored, only a per-store salt + ciphertext
- Every tool call logged to `~/.xcpng-aiops/audit.db` (local SQLite audit DB; relocate with `XCPNG_AIOPS_HOME`)
- Policy rules enforced via `~/.xcpng-aiops/rules.yaml` (deny rules, maintenance windows, risk tiers)
- **Secure by default**: with no `~/.xcpng-aiops/rules.yaml`, high-risk operations are denied unless `XCPNG_AUDIT_APPROVED_BY` names an approver (set `XCPNG_AUDIT_RATIONALE` too). `xcpng-aiops init` seeds a starter rules.yaml; an operator-authored rules file is honoured as-is.
- Budget / runaway guard caps cumulative tool calls and wall-time, and trips on tight task-poll loops
- Undo store records replayable inverse descriptors for `vm_start`/`vm_stop`/`vm_migrate`/`snapshot_create`
- Graduated-autonomy risk tiers gate write operations (require a recorded approver for the highest tiers)

The harness is bundled in the package — no external dependency, no manual setup. See `references/setup-guide.md` for security details.

## Contributing & feature requests

This is a preview — coverage is intentionally focused and **mock-validated only**. **Missing a capability you need, or hit an endpoint that differs on your Xen Orchestra version?** Open an issue or pull request at [github.com/AIops-tools/XCPng-AIops](https://github.com/AIops-tools/XCPng-AIops/issues) — feature requests, contributions, and comments are all welcome.

## License

MIT — [github.com/AIops-tools/XCPng-AIops](https://github.com/AIops-tools/XCPng-AIops)

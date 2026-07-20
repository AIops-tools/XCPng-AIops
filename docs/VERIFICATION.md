# Live verification — xcpng-aiops

`xcpng-aiops` is published and its behaviour is exercised by a **mock-only**
test suite. It has **not** yet been validated end-to-end against a live Xen
Orchestra instance. Until it has, we make no claim that the XO REST `/rest/v0`
paths, action names, and field shapes match a real XO release.

This is the sharpest open question for this tool: the endpoint paths
(`/vms/<id>/actions/snapshot`, `/vm-snapshots/<id>`, `/srs/<id>/actions/rescan`,
`/hosts/<id>/missing_patches`, `/backup/logs`) are modelled against the
documented API, and **action names are known to drift across XO releases**.

This document defines exactly what a live verification run must cover, and the
criteria for recording this tool as live-verified. It is deliberately
checklist-shaped so the result is reproducible and auditable — not a subjective
"seems fine".

## What the mock suite already guarantees

- Every module imports; the CLI builds; every MCP tool carries the
  `@governed_tool` harness marker (`tests/test_smoke.py`).
- The four RCA analyses (`vm_health_rca`, `sr_usage_rca`,
  `backup_failure_rca`, `pool_patch_ha_posture`) are unit-tested against
  synthetic XO payloads, including their thresholds, classifications and
  rankings.
- Write tools carry the correct risk tier and record the correct inverse undo
  descriptor against a mocked connection: `vm_start` ↔ `vm_stop`;
  `vm_migrate` records migrating back to the **captured** source host;
  `snapshot_create` records deleting the **real** snapshot id XO returned.
- `snapshot_delete` / `snapshot_revert` are `high` risk, capture BEFORE state,
  and honestly record **no** undo.
- `dry_run=True` on every write returns a preview, records no undo, and makes no
  write call. It MAY read — that is how it evaluates guards and resolves ids —
  and it is audited like any other governed call, on the CLI as well as MCP.
- `vm_stop` refuses the target's declared `xo_self_vm_uuid` on both the MCP and
  CLI paths and on `dry_run` too, refuses no other uuid, and refuses nothing
  when undeclared. The IP hint never blocks on either path.
- `vm_migrate` stashes the pre-move source host via `capture_prior_state`
  BEFORE the POST, so the inverse is recorded even when the response is lost.

What it does **not** guarantee: that those REST paths, XO action names, RRD
stat shapes and backup-log field names exist as modelled on any real XO build.

It also does **not** guarantee that stopping the Xen Orchestra VM is prevented.
The guard is exact but opt-in: with no `xo_self_vm_uuid` declared on the target,
nothing is refused. XO's REST API has no self endpoint and its static token
carries no claims, so this cannot be discovered today, and the tool fails open
rather than guess. The IP-based `selfVmHint` in the dry-run is advisory only —
it is silent without the guest agent and fires on every VM behind a shared
proxy or NAT. A live run should confirm both: that the declared uuid is refused
and that an undeclared target is not.

## Prerequisites for a live run

Live verification is **not** as cheap as a container here — you need a real
XCP-ng host (or nested XCP-ng) plus a Xen Orchestra instance:

- **Xen Orchestra 5.x** with the REST API `/rest/v0` enabled — XO from sources
  or the Xen Orchestra Appliance. XO is the management plane; per-host XAPI is
  out of scope.
- At least one XCP-ng host in a pool. A **two-host pool** is needed to cover
  migration and version-skew findings; a single host still covers most boxes.
- An XO **authentication token** with least privilege, and a **throwaway test
  VM** you are willing to stop, reboot, snapshot, revert, and migrate.

Never verify against production VMs.

```bash
uv tool install xcpng-aiops
xcpng-aiops init      # XO URL + token, stored encrypted
```

Record the XO version and the XCP-ng version — this tool's main risk is
version drift, so a result without versions is not a usable result.

## Verification checklist

Tick every box. A box that cannot be ticked is a verification gap — record it,
do not silently pass.

### 1. Connectivity (the fastest live gate)
- [ ] `xcpng-aiops doctor` → all green: config, encrypted secret store, XO
      reachable over `/rest/v0`, and a real pool count returned.

### 2. Reads return real, well-shaped data
- [ ] `xcpng-aiops overview` → pools, hosts, VMs by state and SRs match the XO
      UI; no crash on fields this XO release omits.
- [ ] `xcpng-aiops vm list` / `vm get <uuid>` → real VMs with populated uuid,
      name, power state, host and guest-tools status.
- [ ] `xcpng-aiops vm stats <uuid>` → RRD series parse into usable numbers
      (the RRD payload shape is a likely drift point).
- [ ] `xcpng-aiops host list` / `host get <uuid>` / `host missing-patches
      <uuid>` → the patch list matches what XO shows for the host.
- [ ] `xcpng-aiops pool list` / `pool get <uuid>` → real pools.
- [ ] `xcpng-aiops sr list` / `sr get <uuid>` / `sr vdis --sr <uuid>` → SR
      sizes match the XO UI; `--orphaned-only` returns genuinely unattached
      VDIs (no false positives).
- [ ] `xcpng-aiops snapshot list` → existing snapshots are listed with real ids.
- [ ] `xcpng-aiops backup jobs` / `backup logs -n 20` → real XO backup jobs and
      runs (the `/backup/logs` shape is a likely drift point).
- [ ] `xcpng-aiops task list` → in-flight XO tasks appear.

### 3. RCAs judge correctly against reality
- [ ] `xcpng-aiops vm health-rca` → a deliberately halted or paused test VM is
      flagged with the right cause; a healthy VM is not (no false positive).
- [ ] `xcpng-aiops sr usage-rca` → the near-full (≥85%) and critical (≥95%)
      thresholds fire against measured SR fullness; overcommit and orphaned-VDI
      reclaimable bytes are plausible.
- [ ] `xcpng-aiops backup failure-rca` → a genuinely failed backup run is
      classified into the correct bucket (vdi-chain / quiesce / transport /
      storage-full), not "unknown".
- [ ] `xcpng-aiops pool posture` → missing patches, pending reboots and version
      skew match the XO UI for the pool.

### 4. A reversible write + its undo (governance closes the loop)
- [ ] `xcpng-aiops vm stop <test-vm> --dry-run` → prints the API call, changes
      nothing.
- [ ] `xcpng-aiops vm stop <test-vm>` → the VM actually stops; the result
      carries an `_undo_id`; a row lands in `~/.xcpng-aiops/audit.db`.
- [ ] `xcpng-aiops undo apply <id>` → the recorded inverse (`vm_start`) runs and
      the VM comes back up.
- [ ] `xcpng-aiops snapshot create <test-vm> verify-snap` → the recorded undo
      names the **real** snapshot id XO returned (not a guessed one); `undo
      apply` deletes exactly that snapshot.
- [ ] Two-host pool only: `xcpng-aiops vm migrate <test-vm> <other-host>` then
      `undo apply` → the VM returns to its **captured** original host (proves
      the source host was captured, not guessed).
- [ ] `xcpng-aiops sr rescan <sr-uuid>` → completes and is audited as a low-risk
      write.

### 5. Governance actually gates
- [ ] With no `~/.xcpng-aiops/rules.yaml`, a `high`-risk op
      (`snapshot delete` or `snapshot revert`) is **refused** unless
      `XCPNG_AUDIT_APPROVED_BY` is set — secure-by-default.
- [ ] With the approver set, the op succeeds, is audited with approver and
      rationale, and records **no** undo token (it is irreversible and says so).
- [ ] A tight poll loop trips the runaway budget guard rather than hammering XO.
- [ ] A failed operation is audited with `status=error` and records no undo.

### 6. Async XO tasks are polled, not re-issued
- [ ] A long action (migrate, or a snapshot of a large VM) is tracked via
      `xcpng-aiops task list` to completion without the action being re-issued.

### 7. Cleanup
- [ ] Delete the test snapshots; confirm each delete is audited and tagged
      `high`.
- [ ] Return the test VM to its original host and power state.
- [ ] Remove the throwaway XO token from the secret store
      (`xcpng-aiops secret rm <name>`) and revoke it in XO.

## Criteria to consider it live-verified

Record this tool as live-verified **only when all of the following hold**:

1. Every checklist box in sections 1–5 and 7 is ticked against at least one
   real XO instance, with the **XO version and XCP-ng version recorded**
   (e.g. "verified on XO 5.x / XCP-ng 8.3").
2. Sections 4 (migration) and 6 are either ticked, or recorded as explicit
   named gaps if only a single-host pool was available — never quietly skipped.
3. Every REST path or action-name mismatch found during the run is fixed and
   covered by a regression test, and the XO version where it differs is noted.
4. The run is written up in this repo's release notes with the date and
   version, matching how the line records its other live-verified tools.

Until then this document stands as the accurate statement of status.

## Notes for maintainers

- `xcpng-aiops doctor` is the single fastest live entry point; start there.
- Expect the first failures at the **action endpoints**, not the read
  endpoints — XO renames actions between releases more often than it changes
  object shapes.
- The verification story for the whole product line is tracked centrally; add
  this tool's result there once green so the verification-debt ledger stays
  accurate.

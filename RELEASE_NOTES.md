# Release notes — xcpng-aiops 0.3.0

Previous release: 0.2.1.

## In this tool

- **`vm_stop` refuses the Xen Orchestra VM when you declare it.** XO is commonly a VM on the pool it manages, and stopping it kills the request in flight; recovery needs console access. Set `xo_self_vm_uuid` on the target (the `init` wizard now asks) and that uuid is refused exactly. **Undeclared means unguarded** — XO's REST API exposes no self endpoint and its token carries no claims, so there is nothing to infer from, and guessing would be worse than admitting the gap. A dry-run additionally reports an advisory hint when a VM's address matches the configured XO host; it never blocks, because it both false-positives and false-negatives.
- **CLI writes now exit non-zero on a governed error.** Eight commands previously discarded the governed result and printed success — a policy denial, an unreachable XO, or a refused self-target all reported as done.

## Every tool in the line: previews and undetermined outcomes

This release fixes three harness defects that were silently degrading the audit
trail and the undo store.

**A write that loses its response is no longer recorded as a failure.** The
harness assumed a sanitized error meant nothing had happened. That assumption is
false in exactly the case that matters most: when a write severs its own
connection, the request has already landed, the response cannot come back, and
the operation was recorded as `status=error` with **no undo token created at
all**. Transport-level failures are now audited as `status=unknown`, the result
says plainly that the operation may have taken effect and should be verified
before retrying, and a write that stashed its before-state has its inverse
recorded anyway — flagged `effectVerified: false`, which `undo_list` and
`undo_apply` both surface. Existing `undo.db` files are migrated in place; their
rows read as verified, which is accurate, since the old code only ever recorded
on the confirmed path.

**A dry-run no longer writes an undo token.** Previews were recording inverses
built from a before-state they never had: the undo callback's permissive default
filled the gap with a guess, producing a real, applicable token for an operation
that never happened.

**A dry-run no longer demands a named approver.** Requiring an approval in order
to ask whether something needs approval inverts what a preview is for. The tier
is still computed and still audited, so the preview can tell you an approver
will be needed; it just no longer refuses to answer. The write itself is gated
exactly as before.

The invariant, now stated: **a dry_run may read; it must never write.** Guards
run on the preview path, which means a preview can and does report that an
operation would be refused.

## Also line-wide

- **Truncated text now ends in an ellipsis** instead of being cut silently. This
  line already treats a silent cut as a defect for lists; it was doing exactly
  that to strings.
- **Error messages are capped at 800 characters, not 300.** These messages end
  with what to do instead, so the cap was removing the most useful sentence of
  every long refusal.

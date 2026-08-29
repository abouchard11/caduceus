# Flag Lifecycle Ledger

Tracks the complete lifecycle of feature flags and kill switches in the Caduceus system.

## Purpose

Every flag in production must have:
- A clear owner responsible for its lifecycle
- An expiry date or permanent status
- Verified on/off behavior
- Confirmed kill-switch functionality (if applicable)

## Flag Registry

| Flag Name | Owner | Type | Created | Expiry | On Tested | Off Tested | Kill-Switch Verified | Status | Notes |
|-----------|-------|------|---------|--------|-----------|------------|---------------------|--------|-------|
| _example_flag_ | _@username_ | _feature_ | _YYYY-MM-DD_ | _YYYY-MM-DD_ | _✓_ | _✓_ | _N/A_ | _active_ | _Remove this row_ |

### Flag Types

- **feature**: New functionality toggle
- **kill-switch**: Emergency disable for critical path
- **experiment**: A/B test or gradual rollout
- **migration**: Temporary flag during data/code migration
- **circuit-breaker**: Auto-disable on error threshold

### Status Values

- **active**: Flag is in use and monitored
- **deprecated**: Flag is no longer needed, pending removal
- **expired**: Past expiry date, should be removed
- **orphaned**: No owner assigned, needs triage

## Lifecycle Rules

### Creation
1. Every flag must have exactly one owner (GitHub handle or seat name)
2. Feature flags and experiments require an expiry date (max 90 days)
3. Kill-switches and circuit-breakers are permanent until explicitly removed
4. Document the flag in this ledger before merging to main

### Testing Requirements
- **On Tested**: Verify behavior when flag is enabled
- **Off Tested**: Verify behavior when flag is disabled (default state)
- **Kill-Switch Verified**: For kill-switches, confirm emergency disable works end-to-end

### Expiry & Removal
1. Flags past expiry date must be removed within 7 days
2. Owner receives reminder 14 days before expiry
3. Removal requires: code cleanup, ledger update, and verification that default behavior is correct
4. Orphaned flags (no owner) are escalated to council for assignment

### Auditing
- Monthly review of all active flags
- Quarterly cleanup of expired/deprecated flags
- Any flag without verified on/off tests is flagged for immediate attention

## Operational Procedures

### Adding a New Flag

```markdown
| my-new-flag | @owner | feature | 2026-08-27 | 2026-11-25 | ✓ | ✓ | N/A | active | Brief description |
```

### Marking for Deprecation

Change status to `deprecated` and add removal target date in Notes.

### Emergency Kill-Switch Activation

1. Update Notes with timestamp and reason
2. Verify system behavior post-activation
3. Create incident ticket if not already present
4. Schedule post-mortem review

## Integration Points

- **caduceus/config.py**: Flag definitions and defaults
- **caduceus/guard.py**: Kill-switch enforcement
- **tests/**: On/off behavior verification
- **HANDOFF.md**: Flag status in session handoffs

## Ownership Escalation

If a flag owner departs or becomes unresponsive:
1. Flag marked as `orphaned` in ledger
2. Council assigns new owner within 48 hours
3. If no owner found, flag defaults to OFF and is scheduled for removal

---

**Last Audit**: _YYYY-MM-DD_  
**Next Audit Due**: _YYYY-MM-DD_  
**Ledger Maintainer**: Forge (Implementer Seat)

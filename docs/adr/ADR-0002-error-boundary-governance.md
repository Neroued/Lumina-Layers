# ADR-0002: Error Boundary Governance (Catch-All Policy)

## Status
Accepted (2026-04-01)

## Context
- The repository had widespread broad exception handling, reducing diagnosability and consistency.
- Governance was introduced and reduced catch-all handling in governed paths to one point.

## Decision
- Default policy: no broad catch-all in governed API/core hot paths.
- Single design-retained allowlist point:
  - `api/app.py` request middleware top-level `except Exception`.
- Reason for retention:
  - Guarantees structured request-level failure logging and correlation before re-raise.

## Consequences
- Route/core layers must prefer explicit exceptions and domain mapping.
- Catch-all expansion is blocked unless governance baseline and docs are explicitly revised.

## Enforcement
- Governance test: `tests/test_logging_exception_governance_unit.py`
- Governance baseline:
  - `print(` in scope: `0`
  - `except Exception` in scope: `1`

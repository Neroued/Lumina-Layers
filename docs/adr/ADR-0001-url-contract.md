# ADR-0001: Frontend Resource URL Contract

## Status
Accepted (2026-04-01)

## Context
- URL drift previously caused grouped frontend test failures (`absolute` vs `relative` mismatch).
- Current frontend behavior stores resource links in state and passes them across components, making contract consistency mandatory.

## Decision
- Canonical form for frontend state and business logic is **relative URL**.
  - Examples: `/api/files/<id>`, `/output/<name>.zip`
- Absolute URL input is treated as compatibility input and must be normalized before state write/assertion.
- Allowed exception:
  - `frontend/src/__tests__/resource-url.test.ts` may keep absolute URL input samples to verify normalization.

## Consequences
- Prevents environment-coupled test assertions (e.g. `localhost:8000`).
- Keeps frontend behavior stable across local/dev/proxy deployment topologies.
- Any new code asserting absolute backend host literals in tests (outside the allowlisted file) is a contract violation.

## Enforcement
- Guard test: `frontend/src/__tests__/url-localhost-guard.test.ts`
- Normalization tests: `frontend/src/__tests__/resource-url.test.ts`

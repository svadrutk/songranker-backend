---
status: completed
priority: p2
issue_id: "008"
tags: [simplicity, frontend, code-review]
dependencies: []
---

# Problem Statement
The `ReceiptMarquee.tsx` component is more complex than necessary due to runtime randomness and hydration safety boilerplate.

# Findings
- **Location**: `components/ReceiptMarquee.tsx`
- **Evidence**: Use of `shuffle`, `useState`, `useEffect`, and `useMemo` to distribute images.
- **Root Cause**: Trying to achieve randomness while avoiding hydration mismatches.

# Proposed Solutions
1. **Deterministic Distribution**: Use index-based distribution (e.g., `i % 5`) to assign images to columns.
2. **Remove Boilerplate**: Since it's deterministic, the component can render directly on the server and client with the same result, removing `useState` and `useEffect`.

# Acceptance Criteria
- [x] `ReceiptMarquee` component has no `useState` or `useEffect` for image distribution.
- [x] No hydration errors.

# Work Log
### 2026-02-18 - Finding Discovered
**By:** Claude Code (code-simplicity-reviewer)
- Identified over-engineering in component distribution logic.

### 2026-02-18 - Resolved
**By:** Claude Code
- Removed `shuffle`, `useMemo`, `useState`, and `useEffect`.
- Implemented deterministic index-based distribution (`i % 5`).
- Simplified component structure and removed hydration safety boilerplate.

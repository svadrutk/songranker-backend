---
status: pending
priority: p1
issue_id: "002"
tags: [quality, frontend, code-review]
dependencies: []
---

# Problem Statement
A formatting regression was introduced in `lib/api.ts` where a newline was removed, merging a closing brace with an export statement.

# Findings
- **Location**: `lib/api.ts`
- **Evidence**:
  ```typescript
  -};
  -
  -export async function submitFeedback(payload: FeedbackCreate): Promise<FeedbackResponse> {
  +};export async function submitFeedback(payload: FeedbackCreate): Promise<FeedbackResponse> {
  ```

# Proposed Solutions
1. **Revert Change**: Restore the newline and proper spacing.

# Acceptance Criteria
- [ ] `lib/api.ts` follows project formatting standards.
- [ ] No merged lines for braces and exports.

# Work Log
### 2026-02-18 - Finding Discovered
**By:** Claude Code (kieran-typescript-reviewer)
- Identified formatting regression in `lib/api.ts`.

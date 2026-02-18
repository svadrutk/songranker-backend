---
status: pending
priority: p1
issue_id: "003"
tags: [quality, frontend, animation, code-review]
dependencies: []
---

# Problem Statement
The vertical marquee loop has a visible "jump" (glitch) at the reset point.

# Findings
- **Location**: `components/ReceiptMarquee.tsx`
- **Evidence**: The `motion.div` uses `gap-12` (or `gap-10` in latest) but does not account for the gap at the end of the list when duplicating for the loop.
- **Root Cause**: The total height calculated for the `0%` to `-50%` transition doesn't include the final gap, causing a small offset jump during the reset.

# Proposed Solutions
1. **Add Padding**: Add `padding-bottom` to the `motion.div` exactly matching the `gap` value.

# Acceptance Criteria
- [ ] Loop is visually seamless with no jumps.

# Work Log
### 2026-02-18 - Finding Discovered
**By:** Claude Code (kieran-typescript-reviewer)
- Identified loop jump in `ReceiptMarquee.tsx`.

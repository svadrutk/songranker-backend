---
status: resolved
priority: p2
issue_id: "005"
tags: [performance, frontend, code-review]
dependencies: []
---

# Problem Statement
Applying CSS filters to dozens of individual images is computationally expensive and can lead to animation jank.

# Findings
- **Location**: `components/ReceiptMarquee.tsx`
- **Evidence**: `grayscale invert brightness-110` applied to each `Image` component.
- **Impact**: The browser must create and composite a filter layer for every single image (up to 48-60 items).

# Proposed Solutions
1. **Lift Filters**: Apply the filter classes once to the parent `motion.div`.

# Acceptance Criteria
- [x] Marquee uses a single filter layer per column.
- [x] Animation is 60fps on mid-range devices.

# Work Log
### 2026-02-18 - Finding Discovered
**By:** Claude Code (kieran-typescript-reviewer)
- Identified performance bottleneck from individual image filters.

### 2026-02-18 - Resolved
**By:** Claude Code
- Lifted `grayscale invert brightness-110` filters from individual `Image` components to the parent `motion.div` in `ReceiptMarquee.tsx`.
- This reduces the number of filter layers from ~50 to 5 (one per column).

---
status: pending
priority: p2
issue_id: "004"
tags: [performance, backend, code-review]
dependencies: []
---

# Problem Statement
The pre-generated marquee assets are unnecessarily high resolution, consuming excessive VRAM on client devices.

# Findings
- **Location**: `scripts/generate_marquee_assets.py`
- **Evidence**: Images are resized to 800px width.
- **Impact**: 24 unique receipts at 800px width consume ~68MB of VRAM. For a background element with low opacity, this is wasteful and risky for mobile devices.

# Proposed Solutions
1. **Reduce Resolution**: Set `target_width` to 400px in the generation script.
2. **Reduce Quality**: Set WebP quality to 60.

# Acceptance Criteria
- [ ] Assets are generated at 400px width.
- [ ] Total VRAM footprint for the marquee is under 20MB.

# Work Log
### 2026-02-18 - Finding Discovered
**By:** Claude Code (performance-oracle)
- Identified high VRAM usage due to image size.

---
status: pending
priority: p2
issue_id: "006"
tags: [quality, backend, python, code-review]
dependencies: []
---

# Problem Statement
The backend code and scripts contain non-Pythonic patterns and missing type safety.

# Findings
- **Location**: `app/api/v1/image_generation.py`, `scripts/generate_marquee_assets.py`
- **Details**:
  - `render_receipt_html` is marked `async` but is purely synchronous.
  - Script uses `os.path` instead of `pathlib`.
  - Script lacks type hints for parameters.
  - Manual `page.close()` instead of `async with` context manager.

# Proposed Solutions
1. **Refactor**: Apply the "Kieran-approved" Pythonic improvements suggested in the review.

# Acceptance Criteria
- [ ] `render_receipt_html` is a regular `def`.
- [ ] `pathlib.Path` used for all path operations.
- [ ] `async with browser.new_page()` context manager used.
- [ ] All functions have type hints.

# Work Log
### 2026-02-18 - Finding Discovered
**By:** Claude Code (kieran-python-reviewer)
- Identified non-Pythonic patterns.

---
review_agents: [kieran-python-reviewer, kieran-typescript-reviewer, code-simplicity-reviewer, security-sentinel, performance-oracle]
plan_review_agents: [kieran-python-reviewer, kieran-typescript-reviewer, code-simplicity-reviewer]
---

# Review Context

This project is a high-fidelity song ranker. 
The current PR adds a Vertical Receipt Marquee to the landing page.
- The receipts are pre-generated static assets (WebP) to bypass rate limits.
- The frontend uses Framer Motion for high-performance parallax animations.
- Backend refactor allows reusable HTML rendering for receipts via Playwright.
- Accessibility (prefers-reduced-motion) is a priority.

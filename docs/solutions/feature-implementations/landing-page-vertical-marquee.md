---
title: Landing Page Vertical Receipt Marquee Implementation & Optimization
feature: Landing Page Vertical Receipt Marquee
status: solved
problem_types:
  - UI enhancement
  - security fix
  - performance optimization
components_affected:
  - ReceiptMarquee.tsx
  - image_generation.py
  - generate_marquee_assets.py
date: 2026-02-18
---

# Landing Page Vertical Receipt Marquee

## Problem Symptoms
The implementation of a high-fidelity vertical receipt marquee for the landing page encountered several critical issues:
1.  **Hydration Mismatch**: React errors in the browser console ("Text content did not match") caused by non-deterministic layout during SSR.
2.  **Loop Jump**: A visible "glitch" or jump at the point where the infinite scroll resets.
3.  **High VRAM Usage**: Excessive memory consumption (~68MB) on client devices due to high-resolution background assets.
4.  **Security Risk (XSS)**: The receipt generation pipeline was vulnerable to XSS/RCE because Jinja2 auto-escaping was disabled.

## Root Cause Analysis
- **Hydration Mismatch**: Caused by using `shuffle()` and `Math.random()` in the component body, resulting in different initial states between the server and client.
- **Loop Jump**: The `motion.div` animation to `-50%` did not account for the vertical `gap` between the original and duplicated content sets.
- **High VRAM**: Assets were generated at 800px width for a background element that is displayed with low opacity and behind a mask, leading to wasted GPU memory.
- **XSS**: The Jinja2 `Environment` was initialized without `autoescape=True`, allowing unescaped HTML in song/artist names to be executed in the Playwright browser.

## Working Solution

### 1. Security: Enable Jinja2 Auto-escaping
Mitigated XSS/RCE risks by ensuring all template variables are escaped by default.
```python
# app/api/v1/image_generation.py
env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True  # Mitigation for XSS in Playwright context
)
```

### 2. UX: Seamless Loop with Padding
Eliminated the loop jump by adding a `padding-bottom` that exactly matches the `gap` value.
```tsx
// components/ReceiptMarquee.tsx
<motion.div
  style={{ paddingBottom: "2.5rem" }} // Matches gap-10 (2.5rem)
  animate={{ y: ["0%", "-50%"] }}
  transition={{ ease: "linear", duration: 60, repeat: Infinity }}
  className="flex flex-col gap-10"
>
```

### 3. Performance: VRAM Optimization
Reduced asset resolution to 400px and lowered WebP quality, reducing the VRAM footprint by ~75%.
```python
# scripts/generate_marquee_assets.py
target_width = 400
img = img.resize((target_width, int(target_width * aspect_ratio)), Image.Resampling.BILINEAR)
img.save(output_path, "WEBP", quality=60)
```

### 4. Simplicity: Deterministic Distribution
Fixed hydration issues by removing runtime randomness in favor of a deterministic index-based distribution (`i % 5`).
```tsx
// components/ReceiptMarquee.tsx
const columns: string[][] = useMemo(() => {
  const allImages = Array.from({ length: ASSET_COUNT }, (_, i) => `/assets/marquee/receipt_${i}.webp`);
  return Array.from({ length: 5 }, (_, colIndex) => 
    allImages.filter((_, i) => i % 5 === colIndex)
  );
}, []); // ASSET_COUNT is a constant
```

## Prevention Strategies

### Avoiding Hydration Mismatches
- **Defer to Client**: Use a `mounted` state with `useEffect` to only render complex layout components on the client.
  ```tsx
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  ```
- **Stay Deterministic**: Avoid `Math.random()` or shuffles during the render cycle. If randomness is needed, seed it or move it to a client-only effect.

### Seamless Loops in Framer Motion
- **Linear Easing**: Always use `ease: "linear"` for infinite marquees.
- **The Padding Rule**: When using `flex` gaps, the container must have a `padding-bottom` equal to the `gap` so the duplicated set aligns perfectly with the original.

### Security Best Practices
- **Sanitize Early**: Always enable `autoescape=True` when rendering HTML for browser automation (Playwright/Puppeteer).
- **Isolation Boundaries**: When running Playwright with `--no-sandbox` (common in Docker), the **container boundary** becomes the primary security layer. Ensure the process runs with minimal privileges.
- **Network Trade-offs**: While "no-network" mode is ideal for security, image generation often requires fetching external assets (e.g., album art). Limit network access to a strict allowlist of domains (e.g., Spotify CDN) where possible.
- **SSRF Risk**: XSS in a headless browser is high-severity because it can lead to **Server-Side Request Forgery (SSRF)** or local file access if the browser process is not isolated.

## Cross-references
- **Backend PR #6**: [Refactor receipt generation for marquee assets](https://github.com/svadrutk/songranker-backend/pull/6)
- **Frontend PR #2**: [Implement vertical receipt marquee for landing page](https://github.com/svadrutk/songranker-frontend/pull/2)
- **Design Context**: `docs/plans/2026-02-18-feat-landing-page-vertical-receipt-marquee-plan.md`

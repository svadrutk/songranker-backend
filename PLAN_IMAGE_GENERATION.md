# Plan: Server-Side Image Generation for Song Rankings

## Objective
Implement a reliable Python backend endpoint to generate receipt-style PNG images from song ranking data, eliminating client-side mobile rendering issues.

## Tech Stack Selection

### Option 1: Playwright (Recommended)
**Pros:**
- Modern, actively maintained
- Uses real Chromium rendering engine (fonts, images, CSS "just work")
- No CORS issues when fetching album art
- Headless mode is fast and efficient
- Works reliably in Docker/Railway deployments
- ~300MB for browser binaries (acceptable for server deployment)

**Cons:**
- Larger dependency footprint than alternatives
- Requires browser binaries to be installed

**Verdict:** ✅ **Best choice for production**

### Option 2: imgkit + wkhtmltoimage
**Pros:**
- Lightweight
- Battle-tested
- Fast rendering

**Cons:**
- Requires separate `wkhtmltoimage` binary installation
- Less actively maintained
- May have font embedding issues

**Verdict:** ⚠️ Backup option if Playwright fails

### Option 3: Selenium + ChromeDriver
**Pros:**
- Very mature ecosystem
- Widely used

**Cons:**
- Slower than Playwright
- More verbose API
- Heavier resource usage

**Verdict:** ❌ Not recommended

---

## Implementation Plan

### Phase 1: Setup Dependencies
1. Add Playwright to `pyproject.toml`:
   ```toml
   dependencies = [
       ...existing...,
       "playwright>=1.48.0",
       "jinja2>=3.1.4",  # For HTML templating
   ]
   ```

2. Install Playwright browsers:
   ```bash
   uv add playwright jinja2
   playwright install chromium
   ```

### Phase 2: Create HTML Template
Create `app/templates/receipt.html` with:
- Jinja2 template variables for song data, order ID, date/time
- Embedded CSS (using Tailwind-like utility classes or inline styles)
- Self-contained HTML (no external dependencies)
- Receipt design: jagged edge, barcode, song list with album art

### Phase 3: Create API Endpoint
File: `app/api/v1/image_generation.py`

**Endpoint:** `POST /generate-receipt`

**Request Body:**
```json
{
  "songs": [
    {
      "song_id": "uuid",
      "name": "Song Name",
      "artist": "Artist Name",
      "cover_url": "https://...",
      ...
    }
  ],
  "orderId": 1234,
  "dateStr": "01/20/26",
  "timeStr": "14:30"
}
```

**Response:**
- Content-Type: `image/png`
- Binary PNG data

**Logic:**
1. Validate request payload
2. Render Jinja2 template with song data
3. Launch headless Chromium via Playwright
4. Load rendered HTML
5. Wait for fonts + images to load
6. Take screenshot with specific viewport (1080x1200)
7. Return PNG as StreamingResponse

### Phase 4: Update Frontend
File: `songranker-frontend/components/ShareButton.tsx`

**Changes:**
1. Update API endpoint URL to point to Python backend:
   ```tsx
   const response = await fetch(`${BACKEND_URL}/generate-receipt`, {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ songs, orderId, dateStr, timeStr })
   });
   ```
2. Remove client-side `html-to-image` logic
3. Remove hidden `ShareVisual` component from DOM

### Phase 5: Font Handling
**Options:**
1. **Self-host fonts in backend**: Copy Geist fonts to `app/static/fonts/` and reference them in the HTML template
2. **Use Google Fonts CDN**: Simpler but adds network dependency during render
3. **Embed Base64 fonts**: Most reliable but increases HTML size

**Recommendation:** Self-host fonts in `app/static/fonts/` for reliability and speed.

### Phase 6: Deployment Considerations

**Railway/Docker:**
- Playwright browsers require system libraries
- Add to Dockerfile:
  ```dockerfile
  RUN playwright install --with-deps chromium
  ```
- Railway buildpacks should handle this automatically if using standard Python runtime

**Environment Variables:**
- No new env vars needed (uses existing BACKEND_URL)

**Performance:**
- Expected generation time: 500ms - 2s per image
- Consider adding Redis caching for identical song lists

---

## File Structure

```
songranker-backend/
├── app/
│   ├── api/v1/
│   │   ├── image_generation.py  # New endpoint
│   │   └── ...
│   ├── templates/
│   │   └── receipt.html          # New Jinja2 template
│   ├── static/
│   │   └── fonts/                # Self-hosted Geist fonts
│   │       ├── Geist-Black.woff2
│   │       └── GeistMono-Bold.woff2
│   └── ...
└── pyproject.toml                # Updated dependencies
```

---

## Testing Strategy

1. **Local Development:**
   - Run `uvicorn app.main:app --reload`
   - Test endpoint with Postman/curl
   - Verify PNG output quality

2. **Mobile Testing:**
   - Deploy to Railway
   - Test on iOS Safari + Android Chrome
   - Verify fonts, images, and layout are perfect

3. **Performance Testing:**
   - Measure average generation time
   - Test with 10 concurrent requests
   - Monitor memory usage

---

## Rollback Plan

If Playwright fails or is too slow:
1. Try `imgkit` + `wkhtmltoimage`
2. Fall back to client-side generation with simplified design
3. Consider third-party service (e.g., Puppeteer as a Service)

---

## Estimated Timeline

- **Phase 1-2 (Setup + Template):** 30 minutes
- **Phase 3 (API Endpoint):** 45 minutes
- **Phase 4 (Frontend Update):** 15 minutes
- **Phase 5-6 (Fonts + Deployment):** 30 minutes

**Total:** ~2 hours

---

## Next Steps

1. ✅ Review plan
2. Install Playwright + Jinja2
3. Create HTML template
4. Implement API endpoint
5. Update frontend to consume endpoint
6. Test locally
7. Deploy to Railway
8. Test on mobile devices

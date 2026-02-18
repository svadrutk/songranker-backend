import logging
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
from app.core.limiter import limiter

router = APIRouter()

logger = logging.getLogger(__name__)

# Setup Jinja2 environment
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
FONTS_DIR = STATIC_DIR / "fonts"

# Load fonts as base64
def load_font_base64(font_path: Path) -> str:
    with open(font_path, 'rb') as f:
        import base64
        return base64.b64encode(f.read()).decode('utf-8')

GEIST_FONT_BASE64 = load_font_base64(FONTS_DIR / "Geist/variable/Geist[wght].ttf")
GEIST_MONO_FONT_BASE64 = load_font_base64(FONTS_DIR / "GeistMono-Bold.woff2")

env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

class SongData(BaseModel):
    song_id: str
    name: str
    artist: str
    cover_url: Optional[str] = None

class ReceiptRequest(BaseModel):
    songs: List[SongData]
    orderId: int
    dateStr: str
    timeStr: str

def generate_barcode_pattern(songs: List[SongData]) -> List[dict[str, Any]]:
    seed = sum(len(s.name) for s in songs)
    pattern = []
    widths = [1, 2, 4, 6]
    
    for i in range(80):
        width = widths[(seed + i) % 4]
        visible = ((seed * (i + 1)) % 10) > 1
        pattern.append({"width": width, "visible": visible})
        
    return pattern

def render_receipt_html(request: ReceiptRequest) -> str:
    template = env.get_template("receipt.html")
    
    top_10_songs = request.songs[:10]
    barcode_pattern = generate_barcode_pattern(request.songs)
    
    context = {
        "songs": top_10_songs,
        "order_id": str(request.orderId),
        "date_str": str(request.dateStr),
        "time_str": str(request.timeStr),
        "barcode_pattern": barcode_pattern,
        "geist_font_base64": GEIST_FONT_BASE64,
        "geist_mono_font_base64": GEIST_MONO_FONT_BASE64
    }
    
    return template.render(**context)

@limiter.limit("5/minute")
@router.post("/generate-receipt")
async def generate_receipt(request: ReceiptRequest) -> StreamingResponse:
    try:
        logger.info(f"Generating receipt for Order: {request.orderId}, Date: {request.dateStr}, Time: {request.timeStr}")
        
        html_content = render_receipt_html(request)
        
        async with async_playwright() as p:
            # NOTE: --no-sandbox is required for Playwright to run in most Docker/Linux environments
            # without CAP_SYS_ADMIN. Security is maintained by:
            # 1. Container isolation (service runs in a restricted container)
            # 2. Input sanitization (Jinja2 autoescape=True)
            # 3. Minimal browser permissions
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = await browser.new_page(viewport={"width": 1080, "height": 1200})
            
            try:
                # Load HTML content with 10s timeout
                await page.set_content(html_content, wait_until="networkidle", timeout=10000)
                
                # Wait for fonts
                await page.evaluate("document.fonts.ready")
                
                # Get screenshot with 10s timeout
                element = await page.query_selector("body")
                if not element:
                    raise HTTPException(status_code=500, detail="Could not render receipt")
                
                screenshot_bytes = await element.screenshot(type="png", timeout=10000)
                
                logger.info(f"Receipt generated successfully, size: {len(screenshot_bytes)} bytes")
                
                return StreamingResponse(BytesIO(screenshot_bytes), media_type="image/png")
            finally:
                await browser.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating receipt: {e}")
        raise HTTPException(status_code=500, detail=str(e))
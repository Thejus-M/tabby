# Tabby

Split a restaurant bill without the mental math. Photograph the bill, tap who had what, and everyone gets their exact share, taxes included, down to the paisa. Settle with a UPI QR code or send the group a link.

Inspired by [Splitty](https://github.com/xditya/Splitty), rebuilt from scratch in Python.

## How it works

1. **Scan or type** the bill. A local OCR model reads the photo on the server and a rule-based parser turns it into items, quantities, taxes and the printed total. Rows that were hard to read are highlighted next to the photo so you can fix them. No LLM and no outside API is involved.
2. **Add people** and mark who paid. The payer's UPI ID stays on the device.
3. **Assign**: pick one or more people, then tap the items they shared. Use "Uneven split" for portions (e.g. 2 : 1). A progress bar shows how much is still unclaimed.
4. **Settle**: each person sees their total and breakdown, with a UPI QR for the payer. Share a 6-letter code (stored 30 days) or a link that carries the whole bill in the URL fragment (nothing stored).

### Money rules

- All amounts are integer paise. Every division uses one largest-remainder allocator, so per-person totals always add up to the bill total exactly.
- CGST + SGST/UTGST are merged into one GST line and spread over **food** only.
- VAT is spread over **drinks** only, so non-drinkers don't pay liquor tax. Mark drinks with 🍺.
- Service charge can be switched off (it is optional in India under the CCPA guidelines, 2022).
- Taxes on items nobody has claimed yet stay unclaimed instead of being pushed onto others.

## Stack

| Part | Choice |
|------|--------|
| Server | FastAPI, Pydantic, uvicorn, managed with uv |
| Split engine | Pure Python (`src/tabby/engine/`), property-tested with Hypothesis |
| OCR | [RapidOCR](https://github.com/RapidAI/RapidOCR) (PaddleOCR PP-OCR models on ONNX Runtime, CPU), in-process |
| Bill parsing | Pure Python (`src/tabby/scan/`): deskew, row grouping, money parsing, Indian tax and liquor keywords |
| UI | Jinja2 templates + Alpine.js, Tailwind CSS v4 (standalone CLI via `pytailwindcss`, no Node) |
| Shares | SQLite (`aiosqlite`) with TTL, or URL fragment (browser `CompressionStream`) |
| QR | `segno` (server renders SVG, nothing stored) |

The browser holds all bill state (and saves it to `localStorage`). The server is stateless except for shared splits.

## Develop

```bash
uv sync
cp .env.example .env          # optional; defaults work
uv run fastapi dev src/tabby/main.py
```

Open http://localhost:8000. To try it on a phone on the same Wi-Fi, run with `--host 0.0.0.0` and open `http://<your-ip>:8000`.

After changing classes in templates or `app.js`, rebuild the CSS (the built `app.css` is committed):

```bash
uv run tailwindcss -i src/tabby/static/css/input.css -o src/tabby/static/css/app.css --minify
# or add --watch while developing
```

Tests and lint:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Deploy

```bash
docker build -t tabby .
docker run -p 8000:8000 -v tabby-data:/data tabby
```

Run a single process: the rate limiter lives in memory and each process loads its own OCR model. Give it at least 1 GB RAM. A scan takes about 2 s on a laptop CPU. Put it behind HTTPS so the camera, clipboard, Web Share and service worker work on phones.

## Layout

```
src/tabby/
  engine/     money.py, allocate.py (largest remainder), split.py, gst.py
  scan/       image.py (prep), ocr.py (RapidOCR), layout.py (deskew, rows), numbers.py, keywords.py,
              parse.py (rows -> ScannedBill), normalize.py (-> Bill in paise + review flags), service.py
  share/      store.py (SQLite, 6-char codes, TTL)
  routes/     api.py (/api/scan, /api/split, /api/share, /api/qr), pages.py
  templates/  app.html (the 4-step app), shared.html (/s/<code> and /s#d=...)
  static/     css, js/app.js (Alpine components), sw.js, icons, manifest
tests/        engine, fuzz, parser (fake OCR fixtures), API, and a real-OCR smoke test (`pytest -m ocr`)
```

## Privacy

- Bill photos are shrunk in the browser, read by the OCR model inside this server's process, and never written to disk or sent anywhere else.
- UPI IDs never reach the database. For code shares they ride in the URL `#fragment`, which browsers do not send to servers. QR codes are made by a `POST` so the ID stays out of access logs.
- Shared splits are deleted after `SHARE_TTL_DAYS` (default 30).

## Roadmap

- Chat assignment ("Asha had the biryani, Ben and Chitra split the naan")
- Receipt image export for WhatsApp
- "I paid" / "Got it" two-sided payment confirmation on shared splits
- Perspective correction for photos taken at an angle

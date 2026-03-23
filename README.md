# Hope Home Inspections — Agent Advisory Generator

Generates a branded Agent Advisory Brief PDF from inspection reports using Claude AI.

## What it does

Upload your inspection PDFs, enter the year built, and the app:
1. Extracts text from all PDFs
2. Sends them to Claude for analysis
3. Tiers deficiencies, builds negotiation recommendations, and formats the brief
4. Returns a downloadable branded PDF

## Files

- `app.py` — Flask backend, PDF generation, Claude API integration
- `templates/index.html` — Frontend UI
- `logo_white.png` — White logo for PDF header (already included)
- `requirements.txt` — Python dependencies
- `Procfile` — Render start command

## Deploy to Render (free)

1. Create a GitHub account at github.com if you don't have one
2. Create a new repository — name it something like `hope-agent-brief`
3. Upload all files in this folder to that repository
4. Go to render.com and create a free account
5. Click "New" → "Web Service"
6. Connect your GitHub account and select your repository
7. Render will auto-detect Python. Set these fields:
   - **Name:** hope-agent-brief (or anything you like)
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1`
8. Under "Environment Variables" add:
   - Key: `ANTHROPIC_API_KEY`
   - Value: your Claude API key (starts with sk-ant-)
9. Click "Create Web Service"
10. Render builds and deploys. Takes 2-3 minutes.
11. Your app lives at: `https://your-app-name.onrender.com`

## Usage

1. Open your app URL on any device (phone, tablet, desktop)
2. Enter the year built
3. Upload the full home inspection PDF (required)
4. Toggle on and upload any additional inspections completed (4-point, wind mit, WDO)
5. Click "Generate Agent Advisory Brief"
6. Wait 30-60 seconds — PDF downloads automatically

## Cost

- Render free tier: $0/month (app sleeps after 15 min inactivity, wakes in ~30 seconds on next visit)
- Claude API: approximately $0.15 - $0.35 per brief depending on report length

## Render free tier note

On the free tier, the app "sleeps" after 15 minutes of no traffic. The first visit after sleeping takes about 30 seconds to wake up. After that it runs normally. If you want it always-on, Render's paid tier is $7/month.

## Updating the app

Make changes to files in your GitHub repository and Render will auto-redeploy within 2-3 minutes.

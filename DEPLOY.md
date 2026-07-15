# Deploying Trade Lee

Trade Lee is a fully static site — `index.html` + `drills/drills.json`. No server, no build step, no environment variables. Any static host works; these steps use GitHub + Vercel.

## What ships

```
index.html        <- the game (start screen, tutorial, daily, practice)
drills/
  drills.json     <- the drill deck (candles, outcomes, context)
```

`generate_drills.py` is a build-time tool (regenerates `drills/drills.json` from live market data). It is **not** needed at runtime and does not need to run on Vercel — just make sure `drills/drills.json` is committed and up to date before you push.

The other files in this folder (`stock_*.py`, `stock_*.json`) are unrelated to Trade Lee. They won't break anything if included in the repo, but if you want a clean deploy, add a `.gitignore` to exclude them (see step 2).

## 1. One-time: regenerate the deck (optional, only if you want fresh drills)

```bash
python generate_drills.py
```

## 2. Push to GitHub

If this folder isn't a git repo yet:

```bash
git init
git branch -M main
```

Optional — keep the unrelated stock-terminal files out of this repo:

```bash
cat > .gitignore << 'EOF'
__pycache__/
stock_config.json
stock_portfolio.json
stock_trades.json
stock_terminal.py
EOF
```

Commit and push:

```bash
git add index.html drills DEPLOY.md generate_drills.py .gitignore
git commit -m "Trade Lee: static site ready for deploy"
gh repo create trade-lee --public --source=. --remote=origin --push
```

(No `gh` CLI? Create the empty repo at https://github.com/new, then:)

```bash
git remote add origin https://github.com/<your-username>/trade-lee.git
git push -u origin main
```

## 3. Deploy on Vercel

**Option A — CLI (fastest):**

```bash
npm install -g vercel   # if you don't have it
vercel login
vercel --prod
```

When prompted:
- "Link to existing project?" → No (first time)
- "What's your project's name?" → trade-lee (or whatever you like)
- "In which directory is your code located?" → `./`
- Framework preset → **Other** (it's a plain static site, no build command needed)
- Build command → leave blank
- Output directory → leave blank (defaults to root, which is correct)

**Option B — Dashboard:**
1. Go to https://vercel.com/new
2. Import the `trade-lee` GitHub repo
3. Framework Preset: **Other**
4. Root Directory: `./`
5. Build Command: leave empty
6. Output Directory: leave empty
7. Deploy

## 4. Verify after deploy

Open the deployed URL and check:
- `drills/drills.json` loads (Network tab, should be 200 not 404 — confirms the relative fetch path works from the real domain)
- First visit runs the tutorial; reload doesn't re-run it (localStorage survives on the real domain same as on localhost)
- Daily Drill and Practice both play through

## Updating later

Any push to `main` auto-redeploys on Vercel. To ship a fresh drill deck:

```bash
python generate_drills.py
git add drills/drills.json
git commit -m "Refresh drill deck"
git push
```

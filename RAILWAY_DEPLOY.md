# Railway.app Deployment Guide - SpendGuard AI

## Step-by-Step Railway Deployment (5 Minutes)

### Step 1: Push Your Code to GitHub

```bash
# Make sure you're in the project directory
cd /c/Users/adity/OneDrive/Desktop/expense-monitoring-agent

# Add all files
git add .

# Commit
git commit -m "Ready for Railway deployment"

# Push to GitHub
git push origin main
```

### Step 2: Sign Up on Railway

1. Go to **https://railway.app**
2. Click **"Login"** or **"Start a New Project"**
3. Click **"Login with GitHub"**
4. Authorize Railway to access your GitHub account
5. You'll get **$5 free credit** (no credit card required)

### Step 3: Create New Project

1. Click **"New Project"** button (top right)
2. Select **"Deploy from GitHub repo"**
3. You'll see a list of your repositories
4. Find and click **"expense-monitoring-agent"** (or your repo name)
5. Railway will automatically detect it's a Python project

### Step 4: Configure the Service

Railway will auto-detect settings, but verify:

1. **Build Command**: Should auto-detect or you can set:
   ```
   cd backend && pip install -r requirements.txt && python -m spacy download en_core_web_sm
   ```

2. **Start Command**: Should be:
   ```
   cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
   ```

3. Click **"Deploy"**

### Step 5: Wait for Deployment

- Railway will start building (2-5 minutes)
- You'll see logs in real-time
- Wait for "Build successful" and "Deployment live"

### Step 6: Get Your URL

1. Click on your deployed service
2. Go to **"Settings"** tab
3. Scroll to **"Networking"** section
4. Click **"Generate Domain"**
5. You'll get a URL like: `https://spendguard-ai-production.up.railway.app`

### Step 7: Test Your Deployment

Open your Railway URL in browser:
- Backend API: `https://your-app.up.railway.app/`
- API Docs: `https://your-app.up.railway.app/docs`

### Step 8: Deploy Frontend (Optional - Separate Service)

For frontend, you have 2 options:

#### Option A: Serve Frontend from Backend (Easiest)

Update `backend/main.py` to serve static files:

```python
from fastapi.staticfiles import StaticFiles

# Add this after creating the app
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
```

Then access everything at: `https://your-app.up.railway.app/`

#### Option B: Deploy Frontend Separately on Vercel

1. Go to **https://vercel.com**
2. Import your GitHub repo
3. Set **Root Directory** to `frontend`
4. Deploy
5. Update `frontend/app.js` with your Railway backend URL:
   ```javascript
   const API_BASE_URL = 'https://your-app.up.railway.app';
   ```

---

## Troubleshooting

### Issue: Build Fails

**Check logs for errors:**
- Missing dependencies? Add to `requirements.txt`
- Python version issue? Railway uses Python 3.11 by default

### Issue: App Crashes After Deploy

**Check the logs:**
1. Click on your service
2. Go to **"Deployments"** tab
3. Click on latest deployment
4. Check **"View Logs"**

Common fixes:
- Ensure `PORT` environment variable is used: `--port $PORT`
- Check all dependencies are installed

### Issue: Can't Access the App

**Generate a public domain:**
1. Go to **Settings** → **Networking**
2. Click **"Generate Domain"**
3. Wait 1-2 minutes for DNS propagation

---

## Environment Variables (If Needed)

If you need to add environment variables:

1. Click on your service
2. Go to **"Variables"** tab
3. Click **"New Variable"**
4. Add:
   - `PYTHON_VERSION` = `3.11.0`
   - Any other custom variables

---

## Cost & Limits

- **Free Credit**: $5/month
- **Usage**: ~$5-10/month for small apps
- **Sleep Mode**: No sleep on Railway (unlike Render free tier)
- **Always On**: Your app stays running 24/7

---

## Quick Commands Summary

```bash
# 1. Commit and push
git add .
git commit -m "Deploy to Railway"
git push origin main

# 2. Go to railway.app
# 3. New Project → Deploy from GitHub
# 4. Select repo → Deploy
# 5. Generate Domain
# 6. Done!
```

---

## What Railway Does Automatically

✅ Detects Python project
✅ Installs dependencies from requirements.txt
✅ Sets up environment
✅ Provides HTTPS domain
✅ Auto-deploys on git push
✅ Provides logs and monitoring

---

## Next Steps After Deployment

1. ✅ Test all endpoints
2. ✅ Upload sample CSV to verify functionality
3. ✅ Test invoice upload
4. ✅ Share the URL in your hackathon submission
5. ✅ Add deployment URL to README

---

## Pro Tips

💡 **Auto-Deploy**: Every time you push to GitHub, Railway auto-deploys
💡 **Logs**: Always check logs if something doesn't work
💡 **Domains**: You can add custom domains in Settings
💡 **Monitoring**: Railway shows CPU, memory, and network usage
💡 **Rollback**: You can rollback to previous deployments easily

---

## Support

If you get stuck:
- Railway Docs: https://docs.railway.app
- Railway Discord: https://discord.gg/railway
- Check deployment logs for specific errors

Good luck with your deployment! 🚀

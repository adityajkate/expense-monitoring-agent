# Render Deployment Guide - SpendGuard AI

## Deploy to Render.com (Recommended - Most Reliable)

### Step 1: Create render.yaml (Already Done ✅)

The `render.yaml` file is already in your repository.

### Step 2: Sign Up on Render

1. Go to **https://render.com**
2. Click **"Get Started"**
3. Sign up with **GitHub** (free, no credit card required)
4. Authorize Render to access your repositories

### Step 3: Deploy as Blueprint

1. Click **"New +"** (top right)
2. Select **"Blueprint"**
3. Connect your GitHub repository: **expense-monitoring-agent**
4. Render will detect `render.yaml` automatically
5. Click **"Apply"**

### Step 4: Wait for Deployment

- Backend will deploy first (5-7 minutes)
- Frontend will deploy after (1-2 minutes)
- Watch the logs in real-time

### Step 5: Get Your URLs

After deployment completes:
- **Backend API**: `https://spendguard-api.onrender.com`
- **Frontend**: `https://spendguard-frontend.onrender.com`
- **API Docs**: `https://spendguard-api.onrender.com/docs`

### Step 6: Update Frontend API URL (Important!)

After backend is deployed, update the frontend to point to your backend:

Edit `frontend/app.js` line 1:
```javascript
const API_BASE_URL = 'https://spendguard-api.onrender.com';
```

Then commit and push:
```bash
git add frontend/app.js
git commit -m "Update API URL for Render deployment"
git push origin main
```

Render will auto-redeploy the frontend.

---

## Why Render Instead of Railway?

✅ **More Reliable**: Better build system, fewer errors
✅ **Free Tier**: No credit card required
✅ **Auto HTTPS**: Automatic SSL certificates
✅ **Blueprint Support**: Deploys both frontend and backend together
✅ **Better Logs**: Easier to debug issues
✅ **Stable**: Less experimental than Railway's Nixpacks

---

## Render Free Tier Limits

- Services sleep after 15 minutes of inactivity
- First request after sleep takes ~30 seconds to wake up
- 750 hours/month free (enough for demos)
- Automatic deploys on git push

---

## Troubleshooting

### Issue: Build fails with "Tesseract not found"

The render.yaml already includes Tesseract installation. If it fails:
1. Check the build logs
2. Verify the buildCommand in render.yaml includes apt-get install

### Issue: Frontend can't connect to backend

1. Make sure you updated `API_BASE_URL` in frontend/app.js
2. Check CORS is enabled in backend (already done)
3. Verify backend is running at the correct URL

### Issue: Service keeps sleeping

Free tier services sleep after 15 min. Options:
1. Upgrade to paid plan ($7/month)
2. Use a service like UptimeRobot to ping every 14 minutes
3. Accept the sleep behavior for demo purposes

---

## Alternative: Simple Render Deployment (Without Blueprint)

If Blueprint doesn't work, deploy manually:

### Backend:

1. New + → **Web Service**
2. Connect GitHub repo
3. Settings:
   - **Name**: spendguard-api
   - **Root Directory**: (leave blank)
   - **Build Command**:
     ```
     apt-get update && apt-get install -y tesseract-ocr poppler-utils && cd backend && pip install -r requirements.txt && python -m spacy download en_core_web_sm
     ```
   - **Start Command**:
     ```
     cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
     ```
   - **Environment**: Python 3
4. Click **Create Web Service**

### Frontend:

1. New + → **Static Site**
2. Connect GitHub repo
3. Settings:
   - **Name**: spendguard-frontend
   - **Root Directory**: frontend
   - **Build Command**: (leave blank)
   - **Publish Directory**: .
4. Click **Create Static Site**

---

## Expected Timeline

- **Sign up**: 2 minutes
- **Connect GitHub**: 1 minute
- **Backend deployment**: 5-7 minutes
- **Frontend deployment**: 1-2 minutes
- **Total**: ~10 minutes

---

## Next Steps After Deployment

1. ✅ Test backend: `https://your-api.onrender.com/`
2. ✅ Test API docs: `https://your-api.onrender.com/docs`
3. ✅ Update frontend API_BASE_URL
4. ✅ Test frontend: Upload CSV and invoice
5. ✅ Share URLs in hackathon submission

Good luck! 🚀

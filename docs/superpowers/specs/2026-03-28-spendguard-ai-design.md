# SpendGuard AI Design Specification

**Date:** 2026-03-28
**Project Type:** Hackathon MVP (1-day build)
**Target:** End-to-end expense monitoring agent with autonomous action capability

---

## Executive Summary

SpendGuard AI is an autonomous expense monitoring agent that detects fraud and waste in company spending. It ingests transaction data via CSV upload, automatically categorizes expenses, detects anomalies using multi-layer analysis, generates actionable insights, and recommends specific actions—some of which it can execute autonomously.

**Key Differentiator:** Unlike dashboards that only visualize data, SpendGuard AI completes the agent loop: detect → explain → recommend → act.

---

## Goals

**Primary:**
- Build a complete, working system in one day
- Demonstrate autonomous agent capabilities (not just analytics)
- Create a demo that wins hackathon judges

**Success Metrics:**
- Process 500+ transactions in <1 second
- Detect anomalies with clear explanations
- Generate 5+ actionable insights
- Recommend 10+ specific actions
- Execute safe actions autonomously
- Zero crashes during demo

---

## Architecture

**Approach:** Monolithic single-file backend for speed. All processing happens in-memory with no database dependency.

**System Flow:**
```
CSV Upload → FastAPI → Pandas Processing →
(Categorization → Anomaly Detection → Insight Generation → Action Generation) →
JSON Response → Frontend Dashboard
```

**Tech Stack:**
- Backend: Python 3.10+, FastAPI, Pandas, scikit-learn
- Frontend: Plain HTML/JS/CSS with Chart.js
- Storage: In-memory (runtime only)
- Deployment: Local only (`python main.py`)

---

## Data Model

### Transaction Schema
```python
{
    "id": str,
    "date": str,  # YYYY-MM-DD
    "vendor": str,
    "description": str,
    "amount": float,
    "category": str,  # Auto-assigned
    "is_anomaly": bool,
    "anomaly_score": int,  # 0-10
    "anomaly_reasons": list[str],
    "flags": list[str]  # ["global_outlier", "duplicate", etc.]
}
```

### Anomaly Schema
```python
{
    "id": str,
    "date": str,
    "vendor": str,
    "amount": float,
    "category": str,
    "anomaly_score": int,
    "reasons": list[str],
    "confidence": str,  # "High" | "Medium"
    "flags": list[str]
}
```

### Insight Schema
```python
{
    "type": str,  # "cost_spike" | "waste" | "subscription" | "concentration" | "anomaly_summary"
    "severity": str,  # "high" | "medium" | "info"
    "title": str,
    "description": str,
    "impact_amount": float | None,
    "importance_score": float
}
```

### Action Schema
```python
{
    "id": str,
    "type": str,  # "review" | "optimize" | "control"
    "priority": str,  # "high" | "medium" | "low"
    "title": str,
    "description": str,
    "target": str,
    "target_type": str,  # "transaction" | "category" | "vendor" | "group"
    "confidence": str,
    "auto_executable": bool,
    "status": str,  # "pending" | "executed" | "dismissed"
    "impact": float | None
}
```

### Global Cache
```python
CACHE = {
    "df": pd.DataFrame,  # Processed transactions
    "raw_df": pd.DataFrame,  # Original upload
    "summary": dict,
    "insights": list,
    "anomalies": list,
    "actions": list,
    "metadata": {
        "upload_time": datetime,
        "transaction_count": int,
        "date_range": dict,
        "processing_time_ms": int,
        "file_hash": str
    }
}
```

---

## Processing Pipeline

### 1. CSV Parsing & Cleaning

**Input:** CSV file with columns: date, vendor, amount, description (optional)

**Column Fallbacks:**
- `merchant` → `vendor`
- `desc` → `description`

**Cleaning Steps:**
1. Drop rows with null amounts
2. Convert amount to float (skip non-numeric)
3. Normalize vendor: `lower().strip()`
4. Remove negative/zero amounts (or flag separately)
5. Validate minimum 10 transactions

**Edge Cases:**
- Empty CSV → Error: "No valid transactions found"
- Duplicate upload → Check file hash, return "Same file already processed"
- Large file (>10,000 rows) → Error: "File too large for demo"
- All same values → Skip anomaly detection, return info message

### 2. Feature Engineering

**New Columns:**
```python
df['vendor_normalized'] = df['vendor'].str.lower().str.strip()
df['day_of_week'] = pd.to_datetime(df['date']).dt.dayofweek
df['hour'] = pd.to_datetime(df['date'], errors='coerce').dt.hour.fillna(-1)
df['amount_float'] = pd.to_numeric(df['amount'], errors='coerce')
```

**Note:** Only use `hour` if != -1 (many CSVs lack timestamps)

### 3. Categorization (Scored Rule-Based)

**Category Keywords:**
```python
{
    "Cloud Services": ["aws", "azure", "gcp", "cloud", "hosting", "digitalocean"],
    "Travel": ["uber", "lyft", "flight", "hotel", "airbnb", "taxi"],
    "Food & Dining": ["zomato", "swiggy", "restaurant", "cafe", "doordash"],
    "Office Expenses": ["office", "supplies", "furniture", "depot"],
    "Software": ["adobe", "microsoft", "slack", "zoom", "github"],
    "Marketing": ["google ads", "facebook", "linkedin", "mailchimp"],
    "Operations": ["utilities", "rent", "insurance"]
}
```

**Logic:**
1. Score each category by keyword match count in `vendor + description`
2. If tie, return "Miscellaneous"
3. If no matches and amount > $5,000 → "Operations"
4. Otherwise → "Miscellaneous"

### 4. Anomaly Detection (3-Layer System)

**Layer 1: Global Statistical Outliers**
```python
mean_amt = df['amount_float'].mean()
std_amt = max(df['amount_float'].std(), 1e-6)  # Prevent division by zero
z_score = (amount - mean_amt) / std_amt

if z_score > 2.5:
    score += 4
    reasons.append(f"Amount {z_score:.1f}x above global average")
    flags.append("global_outlier")
```

**Layer 2: Category-Specific Outliers**
```python
category_stats = df.groupby('category')['amount_float'].agg(['mean', 'std', 'count'])

if category_count > 5:  # Minimum sample size
    if category_std == 0:
        cat_z = 0
    else:
        cat_z = (amount - category_mean) / category_std

    if cat_z > 2.0:
        score += 3
        reasons.append(f"Amount {cat_z:.1f}x higher than category average")
        flags.append("category_outlier")
```

**Layer 3: Pattern Detection**

*Historical Deviation:*
```python
vendor_df = df[df['vendor_normalized'] == vendor]
if len(vendor_df) > 1:
    # Exclude current row from average
    user_avg = (vendor_df['amount_float'].sum() - amount) / (len(vendor_df) - 1)

    if amount > user_avg * 3:
        score += 3
        reasons.append("Amount 3x higher than historical average for this vendor")
        flags.append("historical_outlier")
```

*Duplicate Detection:*
```python
# Same vendor AND amount within 5% AND within 24 hours
duplicates = set()
for i, row in df.iterrows():
    matches = df[
        (df['vendor_normalized'] == row['vendor_normalized']) &
        (abs(df['amount_float'] - row['amount_float']) / row['amount_float'] < 0.05) &
        (abs((pd.to_datetime(df['date']) - pd.to_datetime(row['date'])).dt.days) < 1) &
        (df.index != i)
    ]
    if len(matches) > 0:
        duplicates.add(i)

if idx in duplicates:
    score += 3
    reasons.append("Potential duplicate transaction detected")
    flags.append("duplicate")
```

*Frequency Spike:*
```python
vendor_daily_counts = df.groupby(['vendor_normalized', df['date'].dt.date]).size()
avg_daily_count = vendor_daily_counts.mean()

if daily_count > avg_daily_count * 2:
    score += 3
    reasons.append("Unusual transaction frequency from this vendor")
    flags.append("frequency_spike")
```

**Scoring:**
- Max score: 10 (capped)
- Anomaly threshold: score >= 5
- Confidence: "High" if score >= 8, else "Medium"

### 5. Insight Generation (Ranked)

**Insight Types:**

**1. Cost Spike Detection**
```python
category_totals = df.groupby('category')['amount_float'].sum()
for cat, total in category_totals.items():
    expected = df[df['category'] == cat]['amount_float'].mean() * count
    if total > expected * 1.3:
        pct_increase = ((total - expected) / expected) * 100
        # Generate insight with importance_score = (total - expected) / df['amount_float'].sum()
```

**2. Waste Detection**
```python
vendor_counts = df.groupby('vendor_normalized').size()
for vendor, count in vendor_counts.items():
    if count > 10:
        avg_amt = df[df['vendor_normalized'] == vendor]['amount_float'].mean()
        total = count * avg_amt
        if avg_amt < 100 and total > 1000:
            # Generate waste insight
```

**3. Subscription Detection**
```python
# Same vendor + same amount (±5%) + intervals 25-35 days + at least 3 occurrences
for vendor in df['vendor_normalized'].unique():
    vendor_txns = df[df['vendor_normalized'] == vendor].sort_values('date')
    amounts = vendor_txns['amount_float'].values
    dates = pd.to_datetime(vendor_txns['date']).values

    # Check for recurring pattern
    if len(amounts) >= 3:
        amount_variance = amounts.std() / amounts.mean()
        if amount_variance < 0.05:  # Within 5%
            intervals = np.diff(dates).astype('timedelta64[D]').astype(int)
            if all(25 <= i <= 35 for i in intervals):
                # Generate subscription insight
```

**4. Concentration Risk**
```python
top_vendor_pct = (df.groupby('vendor_normalized')['amount_float'].sum().max() / df['amount_float'].sum()) * 100
if top_vendor_pct > 50:
    # Generate concentration insight
```

**5. Anomaly Summary**
```python
high_risk_count = len([a for a in anomalies if a['anomaly_score'] >= 8])
if high_risk_count > 0:
    # Generate anomaly summary insight
```

**Ranking:** Sort by `importance_score` (relative to total spend), return top 5

### 6. Action Generation

**From Anomalies:**
- Score >= 8 → "Investigate [vendor] transaction" (REVIEW, high priority, auto-executable)
- Duplicate flag → "Investigate N potential duplicates" (REVIEW, high priority, auto-executable)
- Frequency spike → "Set spending limit for [vendor]" (CONTROL, medium priority, auto-executable)

**From Insights:**
- Cost spike → "Reduce [category] spending" (OPTIMIZE, high priority, manual)
- Subscription → "Review [vendor] subscription" (CONTROL, medium priority, manual)
- Concentration → "Diversify vendor dependencies" (OPTIMIZE, medium priority, manual)

**Auto-Execution (Simulated):**
- REVIEW actions → Flag transaction with "NEEDS_REVIEW" tag
- CONTROL actions (limit) → Suggest spending limit (vendor_avg * 1.5)
- Other actions → Log for manual follow-up

**Ranking:** Sort by priority (high > medium > low) then impact amount, return top 10

---

## API Design

### POST /upload
**Request:** `multipart/form-data` with CSV file
**Response:**
```json
{
    "transaction_count": 450,
    "date_range": {"start": "2026-01-01", "end": "2026-03-28"},
    "processing_time_ms": 234
}
```
**Errors:** 400 (invalid CSV), 500 (processing error)

### GET /dashboard
**Response:** Combined endpoint returning everything
```json
{
    "summary": {
        "total_spend": 125000.50,
        "anomaly_count": 23,
        "anomaly_percentage": 5.1,
        "category_breakdown": {"Cloud Services": 45000, ...},
        "top_vendors": [{"vendor": "AWS", "amount": 45000, "count": 12}, ...]
    },
    "insights": [...],
    "anomalies": [...],
    "actions": [...]
}
```
**Errors:** 400 (no data uploaded)

### GET /transactions
**Query Params:** `?category=Travel&page=1&limit=50`
**Response:**
```json
{
    "transactions": [...],
    "total_pages": 9,
    "current_page": 1,
    "total_count": 450
}
```

### GET /actions
**Response:**
```json
{
    "actions": [...]
}
```

### POST /actions/{action_id}/execute
**Response:**
```json
{
    "status": "executed",
    "message": "Transaction flagged for review",
    "action_taken": "Added 'NEEDS_REVIEW' tag"
}
```
**Errors:** 400 (action not found, not auto-executable)

### POST /actions/{action_id}/dismiss
**Response:**
```json
{
    "status": "dismissed"
}
```

---

## Frontend Design

### Layout (Single Page)

**Header:**
- App title "SpendGuard AI"
- Upload button
- Transaction count + date range

**Section 1: Key Metrics (4 cards)**
- Total Spend
- Anomalies Detected (count + %)
- Categories Tracked
- High-Risk Transactions

**Section 2: Insights Panel**
- 5 insight cards ranked by importance
- Color-coded: red (high), yellow (medium), blue (info)
- Icons: ⚠️ (risk), 💡 (opportunity), 📊 (pattern)
- Click insight → filters anomalies table

**Section 3: Recommended Actions**
- Action cards with priority badges
- Execute/Dismiss buttons
- Visual feedback on execution
- Disabled state for manual-only actions

**Section 4: Spend Breakdown**
- Pie chart: spend by category
- Bar chart: top 10 vendors (sorted descending)
- Interactive: click to filter

**Section 5: Anomalies Table**
- Sortable columns
- Color-coded rows by severity
- Expandable for full explanation
- Quick filter toggle: "Show Only Anomalies"
- Export button

**Section 6: All Transactions Table**
- Paginated (50 per page)
- Filter by category dropdown
- Search by vendor
- Anomaly badges

**Empty States:**
- No anomalies: "✓ No anomalies detected — spending looks normal"
- No insights: "No significant patterns found"
- No data: "Upload a CSV file to get started"

**Processing Feedback:**
- "Processing... 450 transactions analyzed in 234ms"

**Visual Style:**
- Clean, minimal (white background, subtle shadows)
- Chart.js for visualizations
- CSS Grid layout
- No animations (speed over polish)

---

## File Structure

```
expense-monitoring-agent/
├── backend/
│   ├── main.py                 # FastAPI app + all processing logic (~800 lines)
│   ├── data_generator.py       # Synthetic data creation (~150 lines)
│   └── requirements.txt
├── frontend/
│   ├── index.html             # Dashboard UI (~200 lines)
│   ├── app.js                 # API calls + rendering (~250 lines)
│   └── styles.css             # Minimal styling (~150 lines)
├── data/
│   └── sample_expenses.csv    # Pre-generated demo data (450 rows)
├── docs/
│   └── superpowers/
│       ├── specs/
│       │   └── 2026-03-28-spendguard-ai-design.md
│       └── plans/
│           └── 2026-03-28-spendguard-ai-plan.md
└── README.md                  # Setup + demo instructions
```

---

## Demo Script (3 minutes)

**0:00-0:20 - Problem Statement**
"Companies lose millions to fraud and waste because they can't monitor spending in real-time. By the time they discover issues in quarterly audits, the damage is done."

**0:20-0:35 - Upload**
Click upload, select `sample_expenses.csv` (450 transactions)
Show: "Processing... 450 transactions analyzed in 234ms"

**0:35-1:05 - Dashboard Overview**
- Point to metrics: "$125K total spend, 23 anomalies (5.1%)"
- Highlight top insight: "AWS spending spiked 42% - $18K above normal"
- Show category breakdown pie chart

**1:05-1:50 - Drill Into Anomaly**
- Click AWS insight → filters anomalies table
- Show specific transaction: AWS $12,000 charge
- Read explanation: "Amount 5.2x higher than category average, exceeds historical max by 40%"
- Point out confidence: "High"

**1:50-2:15 - Show Intelligence**
- Scroll to other insights: subscription detection, duplicate transactions
- Show frequency spike detection
- Point out concentration risk warning

**2:15-2:25 - Introduce Actions**
"But we don't just show problems — we recommend actions."
Scroll to Actions section

**2:25-2:40 - Autonomous Execution**
- Point to: "Investigate AWS transaction - High priority"
- Click "Execute" button
- Show feedback: "✓ Transaction flagged for review"
- Status changes to "Executed"

**2:40-2:55 - Human-in-Loop**
- Point to: "Reduce Cloud Services spending"
- Show "Execute" is disabled
- Explain: "Financial decisions require human oversight"

**2:55-3:00 - Value Proposition**
"This completes the agent loop: detect anomalies, explain why they matter, recommend specific actions, and execute safe actions immediately. Finance teams go from discovery to resolution in seconds, not days."

---

## Testing Strategy

**Unit Tests (Optional for hackathon):**
- Categorization logic
- Anomaly scoring
- Insight generation

**Integration Tests (Critical):**
- Upload CSV → process → verify response structure
- Execute action → verify state change
- Edge cases: empty CSV, duplicate upload, large file

**Manual Testing Checklist:**
- Upload sample data
- Verify all sections render
- Click insight → table filters
- Execute action → feedback appears
- Dismiss action → status changes
- Export anomalies CSV
- Pagination works
- Search/filter works

**Performance Test:**
- 500 transactions process in <1 second
- Dashboard loads in <500ms
- No memory leaks on multiple uploads

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Demo crashes | Extensive edge case handling, error boundaries |
| Slow processing | In-memory only, optimized pandas operations |
| Bad synthetic data | Generate realistic patterns with known anomalies |
| UI breaks on edge case | Empty states for all sections |
| Action execution fails | Graceful error messages, rollback state |
| Judge uploads bad CSV | Column fallbacks, validation, clear error messages |

---

## Success Criteria

**Technical:**
- ✓ Complete pipeline (upload → process → display → act)
- ✓ Multi-layer anomaly detection
- ✓ Explainable results (reasons + confidence)
- ✓ Autonomous action execution
- ✓ Zero crashes during demo

**Business Value:**
- ✓ Solves real problem (fraud/waste detection)
- ✓ Quantifiable impact (cost savings)
- ✓ Actionable insights (not just visualization)
- ✓ Agent autonomy (completes the loop)

**Demo Quality:**
- ✓ Works reliably
- ✓ Fast (<1s processing)
- ✓ Clear UI
- ✓ Professional polish

**Differentiation:**
- ✓ AI explanations (not just flagging)
- ✓ Multi-layer detection (sophisticated)
- ✓ Insight ranking (prioritization)
- ✓ Action recommendations (decision support)
- ✓ Autonomous execution (agent capability)

---

## Out of Scope (MVP)

- Real bank API integration
- OCR receipt processing
- Deep learning models
- Real-time streaming
- User authentication
- Database persistence
- Multi-user support
- Mobile app
- Email notifications
- ERP integration
- Advanced analytics
- Budget forecasting

---

## Future Enhancements (Post-Hackathon)

1. Bank API integration (Plaid)
2. Receipt OCR with GPT-4 Vision
3. Real-time transaction streaming
4. User authentication & RBAC
5. PostgreSQL persistence
6. Email/Slack alerts
7. Budget management
8. Vendor negotiation recommendations
9. Predictive analytics
10. Mobile app

---

## Conclusion

SpendGuard AI demonstrates a complete autonomous agent: it detects problems, explains them clearly, recommends specific actions, and executes safe actions without human intervention. The monolithic architecture enables rapid development while maintaining demo reliability. The focus on explainability and actionability differentiates it from simple analytics dashboards.

**Winning Formula:** Complete system + Agent autonomy + Clear business value + Reliable demo

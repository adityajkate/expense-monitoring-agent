from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
from datetime import datetime
import hashlib
import io
from ml_categorizer import MLCategorizer
from invoice_ocr import InvoiceOCR
from invoice_matcher import InvoiceMatcher
from fraud_detector import FraudDetector
from audit_trail import AuditTrail

# Initialize FastAPI app
app = FastAPI(
    title="SpendGuard AI",
    description="Autonomous expense monitoring agent",
    version="1.0.0"
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize ML Categorizer
ml_categorizer = MLCategorizer()

# Initialize Invoice OCR
invoice_ocr = InvoiceOCR()

# Initialize Invoice Matcher
invoice_matcher = InvoiceMatcher()

# Initialize Fraud Detector
fraud_detector = FraudDetector()

# Initialize Audit Trail
audit_trail = AuditTrail()

# Global cache for in-memory storage
CACHE = {
    "df": None,
    "raw_df": None,
    "summary": {},
    "insights": [],
    "anomalies": [],
    "actions": [],
    "metadata": {},
    "use_ml": True,  # Flag to enable/disable ML categorization
    "invoices": [],  # Store processed invoices
    "invoice_matches": {},  # Store invoice-transaction matches
    "fraud_alerts": []  # Store fraud detection alerts
}


# ============================================================================
# PROCESSING FUNCTIONS - User Story 1: Upload and Detect Anomalies
# ============================================================================

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """T013: Clean and validate transaction data"""
    # Add description column if missing
    if "description" not in df.columns:
        df["description"] = ""

    # Remove rows with null/zero/negative amounts
    df = df[df["amount"].notna()]
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df[df["amount"] > 0]

    # Normalize vendor names (lowercase, trimmed)
    df["vendor"] = df["vendor"].str.lower().str.strip()

    # Add unique ID
    df["id"] = [f"txn_{i:03d}" for i in range(len(df))]

    return df.reset_index(drop=True)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """T014: Create computed features for analysis"""
    # Vendor normalized (already done in clean_data)
    df["vendor_normalized"] = df["vendor"]

    # Parse dates
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Day of week (0=Monday, 6=Sunday)
    df["day_of_week"] = df["date"].dt.dayofweek

    # Hour (if timestamp available, otherwise -1)
    df["hour"] = df["date"].dt.hour.fillna(-1).astype(int)

    # Amount as float (already done in clean_data)
    df["amount_float"] = df["amount"]

    return df


def categorize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """T015: Categorize transactions using ML or keyword scoring"""

    # Try ML categorization first if model is trained
    if CACHE["use_ml"] and ml_categorizer.is_trained():
        try:
            print("Using ML-based categorization...")
            df = ml_categorizer.predict_batch(df)

            # Rename ML columns to standard columns
            df['category'] = df['category_ml']
            df['category_confidence'] = df['confidence_ml']

            # Flag low-confidence predictions for review
            df['needs_review'] = df['category_confidence'] < 0.7

            print(f"ML categorization complete. Avg confidence: {df['category_confidence'].mean():.2%}")
            return df

        except Exception as e:
            print(f"ML categorization failed: {e}. Falling back to keyword matching...")

    # Fallback to keyword-based categorization
    print("Using keyword-based categorization...")
    CATEGORIES = {
        "Cloud Services": ["aws", "azure", "gcp", "cloud", "hosting", "digitalocean", "heroku", "linode"],
        "Travel": ["uber", "lyft", "flight", "hotel", "airbnb", "taxi", "airline", "booking", "delta", "marriott"],
        "Food & Dining": ["starbucks", "chipotle", "subway", "panera", "restaurant", "cafe", "zomato", "swiggy", "doordash"],
        "Office Expenses": ["office", "supplies", "furniture", "depot", "staples", "ikea"],
        "Software": ["adobe", "microsoft", "slack", "zoom", "github", "atlassian", "jetbrains"],
        "Marketing": ["google ads", "facebook", "linkedin", "mailchimp", "hubspot", "salesforce"],
        "Operations": ["utilities", "rent", "insurance", "payroll", "legal", "accounting", "electric", "internet"]
    }

    def assign_category(row):
        vendor_desc = (str(row["vendor"]) + " " + str(row["description"])).lower()
        scores = {}

        for category, keywords in CATEGORIES.items():
            score = sum(1 for kw in keywords if kw in vendor_desc)
            if score > 0:
                scores[category] = score

        if not scores:
            # No keywords matched
            if row["amount"] > 5000:
                return "Operations"
            return "Miscellaneous"

        # Get max score
        max_score = max(scores.values())
        top_categories = [cat for cat, score in scores.items() if score == max_score]

        # If tie, return Miscellaneous
        if len(top_categories) > 1:
            return "Miscellaneous"

        return top_categories[0]

    df["category"] = df.apply(assign_category, axis=1)
    df["category_confidence"] = 0.85  # Fixed confidence for keyword method
    df["needs_review"] = False

    return df


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """T016-T018: 3-layer anomaly detection"""
    # Initialize anomaly fields
    df["is_anomaly"] = False
    df["anomaly_score"] = 0
    df["anomaly_reasons"] = [[] for _ in range(len(df))]
    df["flags"] = [[] for _ in range(len(df))]

    # Layer 1: Global statistical outliers (T016)
    mean_amt = df["amount_float"].mean()
    std_amt = max(df["amount_float"].std(), 1e-6)  # Prevent division by zero

    for idx, row in df.iterrows():
        z_score = (row["amount_float"] - mean_amt) / std_amt

        if z_score > 2.5:
            df.at[idx, "anomaly_score"] += 4
            df.at[idx, "anomaly_reasons"].append(f"Amount {z_score:.1f}x above global average")
            df.at[idx, "flags"].append("global_outlier")

    # Layer 2: Category-specific outliers (T017)
    category_stats = df.groupby("category")["amount_float"].agg(["mean", "std", "count"])

    for idx, row in df.iterrows():
        cat = row["category"]
        if cat in category_stats.index:
            cat_mean = category_stats.loc[cat, "mean"]
            cat_std = category_stats.loc[cat, "std"]
            cat_count = category_stats.loc[cat, "count"]

            if cat_count >= 5:  # Minimum sample size
                if cat_std == 0:
                    cat_z = 0
                else:
                    cat_z = (row["amount_float"] - cat_mean) / cat_std

                if cat_z > 2.0:
                    df.at[idx, "anomaly_score"] += 3
                    df.at[idx, "anomaly_reasons"].append(f"Amount {cat_z:.1f}x higher than category average")
                    df.at[idx, "flags"].append("category_outlier")

    # Layer 3: Pattern detection (T018)
    # Historical deviation
    for vendor in df["vendor_normalized"].unique():
        vendor_df = df[df["vendor_normalized"] == vendor]
        if len(vendor_df) > 1:
            for idx in vendor_df.index:
                # Exclude current row from average
                other_amounts = vendor_df[vendor_df.index != idx]["amount_float"]
                if len(other_amounts) > 0:
                    user_avg = other_amounts.mean()
                    if df.at[idx, "amount_float"] > user_avg * 3:
                        df.at[idx, "anomaly_score"] += 3
                        df.at[idx, "anomaly_reasons"].append("Amount 3x higher than historical average for this vendor")
                        df.at[idx, "flags"].append("historical_outlier")

    # Duplicate detection
    duplicates = set()
    for i in range(len(df)):
        for j in range(i + 1, len(df)):
            if (df.iloc[i]["vendor_normalized"] == df.iloc[j]["vendor_normalized"] and
                abs(df.iloc[i]["amount_float"] - df.iloc[j]["amount_float"]) / df.iloc[i]["amount_float"] < 0.05 and
                abs((df.iloc[i]["date"] - df.iloc[j]["date"]).days) < 1):
                duplicates.add(i)
                duplicates.add(j)

    for idx in duplicates:
        df.at[idx, "anomaly_score"] += 3
        df.at[idx, "anomaly_reasons"].append("Potential duplicate transaction detected")
        df.at[idx, "flags"].append("duplicate")

    # Frequency spike
    df["date_only"] = df["date"].dt.date
    vendor_daily_counts = df.groupby(["vendor_normalized", "date_only"]).size()

    for idx, row in df.iterrows():
        vendor = row["vendor_normalized"]
        date = row["date_only"]
        daily_count = vendor_daily_counts.get((vendor, date), 0)

        vendor_counts = vendor_daily_counts[vendor_daily_counts.index.get_level_values(0) == vendor]
        if len(vendor_counts) > 1:
            avg_daily_count = vendor_counts.mean()
            if daily_count > avg_daily_count * 2:
                df.at[idx, "anomaly_score"] += 3
                df.at[idx, "anomaly_reasons"].append("Unusual transaction frequency from this vendor")
                df.at[idx, "flags"].append("frequency_spike")

    return df


def assign_anomaly_scores(df: pd.DataFrame) -> pd.DataFrame:
    """T019: Assign final scores and confidence levels"""
    # Cap scores at 10
    df["anomaly_score"] = df["anomaly_score"].clip(upper=10)

    # Flag as anomaly if score >= 5
    df["is_anomaly"] = df["anomaly_score"] >= 5

    # Assign confidence
    df["confidence"] = df["anomaly_score"].apply(
        lambda score: "High" if score >= 8 else ("Medium" if score >= 5 else "")
    )

    return df


def generate_explanations(df: pd.DataFrame) -> pd.DataFrame:
    """T020: Ensure human-readable explanations exist"""
    # Explanations are already generated in detect_anomalies
    # This function ensures they're properly formatted
    for idx, row in df.iterrows():
        if row["is_anomaly"] and not row["anomaly_reasons"]:
            df.at[idx, "anomaly_reasons"] = ["Anomaly detected based on statistical analysis"]

    return df


# ============================================================================
# PROCESSING FUNCTIONS - User Story 2: Generate Actionable Insights
# ============================================================================

def generate_insights(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Generate ranked insights from transaction data"""
    insights = []
    total_spend = df["amount_float"].sum()

    # T027: Cost spike detection
    try:
        cost_spikes = detect_cost_spikes(df, total_spend)
        print(f"DEBUG: Cost spikes detected: {len(cost_spikes)}")
        insights.extend(cost_spikes)
    except Exception as e:
        print(f"ERROR in detect_cost_spikes: {e}")
        import traceback
        traceback.print_exc()

    # T028: Subscription detection
    insights.extend(detect_subscriptions(df, total_spend))

    # T029: Anomaly summary
    insights.extend(generate_anomaly_summary(df, total_spend))

    # T030: Rank by importance score
    insights.sort(key=lambda x: x["importance_score"], reverse=True)

    print(f"DEBUG: Total insights before limit: {len(insights)}")
    return insights[:10]  # Return top 10


def detect_cost_spikes(df: pd.DataFrame, total_spend: float) -> List[Dict[str, Any]]:
    """T027: Detect category spending spikes using percentile-based baseline"""
    insights = []
    category_stats = df.groupby("category")["amount_float"].agg(["sum", "mean", "count"])

    for category, stats in category_stats.iterrows():
        if stats["count"] >= 10:  # Minimum sample size for reliable detection
            # Get all amounts for this category
            category_amounts = df[df["category"] == category]["amount_float"].values

            # Use 25th percentile as baseline (typical lower-end transaction)
            # This is more robust to high-value outliers
            baseline_amount = np.percentile(category_amounts, 25)
            actual_total = stats["sum"]

            # Expected spend = baseline * count (conservative estimate)
            expected_total = baseline_amount * stats["count"]

            # Detect spike: actual is significantly higher than conservative baseline
            if actual_total > expected_total * 1.35:  # 35% above conservative baseline
                pct_increase = ((actual_total - expected_total) / expected_total) * 100
                impact_amount = actual_total - expected_total
                importance_score = impact_amount / total_spend

                severity = "high" if importance_score > 0.15 else "medium"

                insights.append({
                    "type": "cost_spike",
                    "severity": severity,
                    "title": f"{category} spending spiked {pct_increase:.0f}%",
                    "description": f"{category} category spent ${actual_total:,.2f} this period, which is ${impact_amount:,.2f} ({pct_increase:.0f}%) above the expected ${expected_total:,.2f} based on typical transaction amounts (baseline: ${baseline_amount:.2f}). Review for unnecessary spending or vendor price increases.",
                    "impact_amount": impact_amount,
                    "importance_score": importance_score
                })
                print(f"DEBUG: Cost spike detected for {category}: {pct_increase:.0f}% increase, importance: {importance_score:.4f}")

    print(f"DEBUG: detect_cost_spikes returning {len(insights)} insights")
    return insights


def detect_subscriptions(df: pd.DataFrame, total_spend: float) -> List[Dict[str, Any]]:
    """T028: Detect recurring subscription patterns"""
    insights = []

    for vendor in df["vendor_normalized"].unique():
        vendor_txns = df[df["vendor_normalized"] == vendor].sort_values("date")

        if len(vendor_txns) >= 3:
            amounts = vendor_txns["amount_float"].values
            dates = pd.to_datetime(vendor_txns["date"]).values

            # Check amount consistency (within 5%)
            amount_variance = amounts.std() / amounts.mean() if amounts.mean() > 0 else 1
            if amount_variance < 0.05:
                # Check date intervals (25-35 days)
                intervals = np.diff(dates).astype('timedelta64[D]').astype(int)
                if len(intervals) > 0 and all(25 <= i <= 35 for i in intervals):
                    impact_amount = amounts.mean() * 12  # Annual cost
                    importance_score = impact_amount / total_spend

                    insights.append({
                        "type": "subscription",
                        "severity": "medium",
                        "title": f"Recurring ${amounts.mean():.2f} charge from {vendor.title()} detected",
                        "description": f"Detected recurring pattern: {vendor.title()} charges ${amounts.mean():.2f} approximately every 30 days ({len(amounts)} occurrences). Estimated annual cost: ${impact_amount:,.2f}.",
                        "impact_amount": impact_amount,
                        "importance_score": importance_score
                    })

    return insights


def generate_anomaly_summary(df: pd.DataFrame, total_spend: float) -> List[Dict[str, Any]]:
    """T029: Generate summary of high-risk anomalies"""
    insights = []
    high_risk_anomalies = df[df["anomaly_score"] >= 8]

    if len(high_risk_anomalies) > 0:
        high_risk_count = len(high_risk_anomalies)
        total_count = len(df)
        percentage = (high_risk_count / total_count) * 100
        impact_amount = high_risk_anomalies["amount_float"].sum()
        importance_score = impact_amount / total_spend

        severity = "high" if percentage > 5 else "info"

        insights.append({
            "type": "anomaly_summary",
            "severity": severity,
            "title": f"{high_risk_count} high-risk transactions detected ({percentage:.1f}% of total)",
            "description": f"Detected {high_risk_count} high-risk anomalies out of {total_count} transactions ({percentage:.1f}%). These transactions have anomaly scores ≥8 and require immediate review. Total value: ${impact_amount:,.2f}.",
            "impact_amount": impact_amount,
            "importance_score": importance_score
        })

    return insights


# ============================================================================
# PROCESSING FUNCTIONS - User Story 3: Execute Autonomous Actions
# ============================================================================

def generate_actions(df: pd.DataFrame, insights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate recommended actions from anomalies and insights"""
    actions = []
    action_id_counter = 1

    # T037: Generate actions from anomalies (score >= 8)
    high_risk_anomalies = df[df["anomaly_score"] >= 8]
    for idx, row in high_risk_anomalies.iterrows():
        actions.append({
            "id": f"act_{action_id_counter:03d}",
            "type": "review",
            "priority": "high",
            "title": f"Investigate {row['vendor'].title()} transaction",
            "description": f"Review ${row['amount_float']:,.2f} {row['vendor'].title()} charge on {row['date'].strftime('%Y-%m-%d')} - flagged as high-risk anomaly (score: {row['anomaly_score']}/10)",
            "target": row['id'],
            "target_type": "transaction",
            "confidence": row['confidence'],
            "auto_executable": True,
            "status": "pending",
            "impact": row['amount_float']
        })
        action_id_counter += 1

    # T038: Generate actions from insights
    for insight in insights:
        if insight["type"] == "cost_spike":
            # Extract category from title
            category = insight["title"].split(" spending")[0]
            actions.append({
                "id": f"act_{action_id_counter:03d}",
                "type": "optimize",
                "priority": "high" if insight["severity"] == "high" else "medium",
                "title": f"Reduce {category} spending",
                "description": f"{category} spending is {insight['title'].split('spiked ')[1]} - consider reviewing vendor contracts or reducing usage. Potential savings: ${insight['impact_amount']:,.2f}",
                "target": category,
                "target_type": "category",
                "confidence": "High",
                "auto_executable": False,
                "status": "pending",
                "impact": insight["impact_amount"]
            })
            action_id_counter += 1

        elif insight["type"] == "subscription":
            # Extract vendor from title
            vendor = insight["title"].split("from ")[1].split(" detected")[0]
            amount = float(insight["title"].split("$")[1].split(" ")[0])
            actions.append({
                "id": f"act_{action_id_counter:03d}",
                "type": "control",
                "priority": "medium",
                "title": f"Review {vendor} subscription",
                "description": f"Recurring ${amount:.2f} charge detected from {vendor}. Verify if subscription is still needed. Annual cost: ${insight['impact_amount']:,.2f}",
                "target": vendor.lower(),
                "target_type": "vendor",
                "confidence": "High",
                "auto_executable": False,
                "status": "pending",
                "impact": insight["impact_amount"]
            })
            action_id_counter += 1

    # T040: Rank actions by priority then impact
    priority_order = {"high": 3, "medium": 2, "low": 1}
    actions.sort(key=lambda x: (priority_order[x["priority"]], x["impact"] or 0), reverse=True)

    return actions[:10]  # Return top 10


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "message": "SpendGuard AI API is running"}


@app.get("/ml-status")
async def ml_status():
    """Get ML model status and performance metrics"""
    is_trained = ml_categorizer.is_trained()

    status = {
        "ml_enabled": CACHE["use_ml"],
        "model_trained": is_trained,
        "model_path": ml_categorizer.model_path,
        "categorization_method": "ML-based" if (CACHE["use_ml"] and is_trained) else "Keyword-based"
    }

    # Add performance metrics if data is loaded
    if CACHE["df"] is not None and "category_confidence" in CACHE["df"].columns:
        df = CACHE["df"]
        status["performance"] = {
            "avg_confidence": f"{df['category_confidence'].mean():.2%}",
            "min_confidence": f"{df['category_confidence'].min():.2%}",
            "max_confidence": f"{df['category_confidence'].max():.2%}",
            "low_confidence_count": int((df['category_confidence'] < 0.7).sum()),
            "total_transactions": len(df)
        }

    return status


@app.post("/upload-invoice")
async def upload_invoice(file: UploadFile = File(...)):
    """
    Upload and process invoice PDF or image

    Accepts: PDF, JPG, PNG, TIFF
    Returns: Extracted invoice data and created transactions
    """
    try:
        # Validate file type
        allowed_types = {
            'application/pdf': 'pdf',
            'image/jpeg': 'image',
            'image/jpg': 'image',
            'image/png': 'image',
            'image/tiff': 'image'
        }

        file_type = allowed_types.get(file.content_type)
        if not file_type:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file.content_type}. Supported: PDF, JPG, PNG, TIFF"
            )

        # Read file
        file_bytes = await file.read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Check if already processed
        existing = next((inv for inv in CACHE["invoices"] if inv.get("file_hash") == file_hash), None)
        if existing:
            return {
                "status": "already_processed",
                "invoice_data": existing,
                "message": "This invoice was already processed"
            }

        # Extract data using OCR
        start_time = datetime.now()

        try:
            invoice_data = invoice_ocr.extract_invoice_data(file_bytes, file_type)
        except RuntimeError as e:
            raise HTTPException(
                status_code=503,
                detail=str(e) + " Please install Tesseract OCR. See TESSERACT_INSTALL.md"
            )

        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)

        # Add metadata
        invoice_data['file_name'] = file.filename
        invoice_data['file_hash'] = file_hash
        invoice_data['file_type'] = file_type
        invoice_data['processing_time_ms'] = processing_time

        # Log invoice upload to audit trail
        audit_trail.log_invoice_upload(
            invoice_id=file_hash,
            file_name=file.filename,
            file_size=len(file_bytes),
            user_id='system'
        )

        # Log invoice processing
        audit_trail.log_invoice_processing(
            invoice_id=file_hash,
            extraction_data=invoice_data,
            confidence=invoice_data['confidence'],
            processing_time_ms=processing_time
        )

        # Run fraud detection
        fraud_result = fraud_detector.analyze_invoice(
            invoice=invoice_data,
            historical_invoices=CACHE["invoices"],
            transactions=CACHE["df"]
        )

        # Log fraud alerts if any
        for alert in fraud_result['alerts']:
            audit_trail.log_fraud_alert(
                invoice_id=file_hash,
                alert_type=alert['alert_type'],
                severity=alert['severity'],
                confidence=alert['confidence'],
                description=alert['description']
            )

        # Store fraud result
        invoice_data['fraud_analysis'] = fraud_result
        CACHE["fraud_alerts"].extend(fraud_result['alerts'])

        # Create transaction from invoice
        transaction = {
            'date': invoice_data.get('date', datetime.now().strftime('%Y-%m-%d')),
            'vendor': invoice_data['vendor'],
            'amount': invoice_data['amounts'].get('total', 0),
            'description': f"Invoice {invoice_data.get('invoice_number', 'N/A')}",
            'source': 'invoice_ocr',
            'invoice_id': file_hash,
            'confidence': invoice_data['confidence']
        }

        # Store invoice
        CACHE["invoices"].append(invoice_data)

        # Add to transactions if we have existing data
        if CACHE["df"] is not None:
            # Create new transaction row
            new_row = pd.DataFrame([transaction])

            # Process it through the pipeline
            new_row = clean_data(new_row)
            new_row = engineer_features(new_row)
            new_row = categorize_transactions(new_row)
            new_row = detect_anomalies(new_row)
            new_row = assign_anomaly_scores(new_row)
            new_row = generate_explanations(new_row)

            # Append to existing data
            CACHE["df"] = pd.concat([CACHE["df"], new_row], ignore_index=True)

            # Regenerate insights and actions
            CACHE["insights"] = generate_insights(CACHE["df"])
            CACHE["actions"] = generate_actions(CACHE["df"], CACHE["insights"])

            # Update anomalies
            anomalies_df = CACHE["df"][CACHE["df"]["is_anomaly"]].copy()
            CACHE["anomalies"] = anomalies_df.to_dict("records")

            # Match invoice to transactions
            match_result = invoice_matcher.match_invoices_to_transactions(
                invoices=[invoice_data],
                transactions=CACHE["df"]
            )

            # Store match results
            if match_result['matches']:
                match = match_result['matches'][0]
                CACHE["invoice_matches"][file_hash] = match

                # Log the match
                audit_trail.log_invoice_match(
                    invoice_id=file_hash,
                    transaction_id=match['transaction_id'],
                    match_score=match['match_score'],
                    match_type=match['match_type']
                )

            invoice_data['match_result'] = match_result

        return {
            "status": "success",
            "invoice_data": invoice_data,
            "transaction": transaction,
            "fraud_analysis": fraud_result,
            "processing_time_ms": processing_time,
            "message": f"Invoice processed successfully. Confidence: {invoice_data['confidence']:.0%}, Risk: {fraud_result['risk_level']}"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invoice processing failed: {str(e)}")


@app.get("/invoices")
async def get_invoices():
    """Get all processed invoices"""
    return {
        "invoices": CACHE["invoices"],
        "total_count": len(CACHE["invoices"])
    }


@app.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str):
    """Get specific invoice by ID (file hash)"""
    invoice = next((inv for inv in CACHE["invoices"] if inv.get("file_hash") == invoice_id), None)

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return invoice


@app.get("/invoice-matches")
async def get_invoice_matches():
    """Get all invoice-to-transaction matches"""
    return {
        "matches": list(CACHE["invoice_matches"].values()),
        "total_count": len(CACHE["invoice_matches"])
    }


@app.get("/invoice-matches/{invoice_id}")
async def get_invoice_match(invoice_id: str):
    """Get match details for specific invoice"""
    match = CACHE["invoice_matches"].get(invoice_id)

    if not match:
        raise HTTPException(status_code=404, detail="No match found for this invoice")

    return match


@app.post("/match-invoices")
async def match_all_invoices():
    """Match all invoices to transactions"""
    if CACHE["df"] is None or not CACHE["invoices"]:
        raise HTTPException(
            status_code=400,
            detail="No transactions or invoices available for matching"
        )

    # Run matching for all invoices
    match_result = invoice_matcher.match_invoices_to_transactions(
        invoices=CACHE["invoices"],
        transactions=CACHE["df"]
    )

    # Store matches
    for match in match_result['matches']:
        CACHE["invoice_matches"][match['invoice_id']] = match

        # Log each match
        audit_trail.log_invoice_match(
            invoice_id=match['invoice_id'],
            transaction_id=match['transaction_id'],
            match_score=match['match_score'],
            match_type=match['match_type']
        )

    return match_result


@app.get("/fraud-alerts")
async def get_fraud_alerts():
    """Get all fraud detection alerts"""
    return {
        "alerts": CACHE["fraud_alerts"],
        "total_count": len(CACHE["fraud_alerts"]),
        "critical_count": len([a for a in CACHE["fraud_alerts"] if a['severity'] == 'critical']),
        "high_count": len([a for a in CACHE["fraud_alerts"] if a['severity'] == 'high'])
    }


@app.get("/fraud-alerts/{invoice_id}")
async def get_invoice_fraud_alerts(invoice_id: str):
    """Get fraud alerts for specific invoice"""
    invoice = next((inv for inv in CACHE["invoices"] if inv.get("file_hash") == invoice_id), None)

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    fraud_analysis = invoice.get('fraud_analysis', {})

    return fraud_analysis


@app.get("/audit-trail/{invoice_id}")
async def get_invoice_audit_trail(invoice_id: str):
    """Get complete audit trail for an invoice"""
    history = audit_trail.get_invoice_history(invoice_id)

    if not history:
        raise HTTPException(status_code=404, detail="No audit trail found for this invoice")

    return {
        "invoice_id": invoice_id,
        "history": history,
        "event_count": len(history)
    }


@app.get("/audit-trail/user/{user_id}")
async def get_user_audit_trail(
    user_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Get audit trail for a specific user"""
    history = audit_trail.get_user_activity(user_id, start_date, end_date)

    return {
        "user_id": user_id,
        "history": history,
        "event_count": len(history)
    }


@app.get("/compliance-report")
async def get_compliance_report(
    start_date: str,
    end_date: str
):
    """Generate compliance report for date range"""
    report = audit_trail.generate_compliance_report(start_date, end_date)

    return report


@app.post("/export-audit-log")
async def export_audit_log(
    output_path: str = "./data/audit_export.csv",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    format: str = "csv"
):
    """Export audit log to file"""
    try:
        file_path = audit_trail.export_audit_log(
            output_path=output_path,
            start_date=start_date,
            end_date=end_date,
            format=format
        )

        return {
            "status": "success",
            "file_path": file_path,
            "message": f"Audit log exported to {file_path}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@app.post("/clear")
async def clear_cache():
    """Clear all cached data"""
    CACHE["df"] = None
    CACHE["raw_df"] = None
    CACHE["summary"] = {}
    CACHE["insights"] = []
    CACHE["anomalies"] = []
    CACHE["actions"] = []
    CACHE["metadata"] = {}
    CACHE["invoices"] = []
    CACHE["invoice_matches"] = {}
    CACHE["fraud_alerts"] = []
    return {"status": "cleared", "message": "All data cleared"}


@app.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    """
    Upload and process CSV file with transaction data

    Required columns: date, vendor, amount
    Optional columns: description
    """
    try:
        # Read file content
        content = await file.read()
        file_hash = hashlib.sha256(content).hexdigest()

        # Allow re-upload by clearing cache if same file
        if CACHE["metadata"].get("file_hash") == file_hash:
            # Clear cache to allow re-processing
            CACHE["df"] = None
            CACHE["raw_df"] = None
            CACHE["summary"] = {}
            CACHE["insights"] = []
            CACHE["anomalies"] = []
            CACHE["actions"] = []
            CACHE["metadata"] = {}

        # Parse CSV
        df = pd.read_csv(io.BytesIO(content))

        # Validate required columns
        required_cols = ["date", "vendor", "amount"]
        # Handle column variations
        col_mapping = {
            "merchant": "vendor",
            "desc": "description"
        }

        # Apply column mapping
        df = df.rename(columns=col_mapping)

        # Check for required columns
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise HTTPException(
                status_code=400,
                detail=f"CSV must contain columns: {', '.join(required_cols)}"
            )

        # Validate transaction count
        if len(df) < 10:
            raise HTTPException(
                status_code=400,
                detail="No valid transactions found (minimum 10 required)"
            )
        if len(df) > 10000:
            raise HTTPException(
                status_code=400,
                detail="File too large for demo - maximum 10,000 transactions"
            )

        # Store raw dataframe
        CACHE["raw_df"] = df.copy()

        # Start processing timer
        start_time = datetime.now()

        # T013: CSV parsing and cleaning
        df = clean_data(df)

        # T014: Feature engineering
        df = engineer_features(df)

        # T015: Categorization
        df = categorize_transactions(df)

        # T016-T018: 3-layer anomaly detection
        df = detect_anomalies(df)

        # T019: Anomaly scoring and confidence
        df = assign_anomaly_scores(df)

        # T020: Human-readable explanations
        df = generate_explanations(df)

        # Store processed dataframe
        CACHE["df"] = df

        # T031: Generate insights
        CACHE["insights"] = generate_insights(df)

        # T041: Generate actions
        CACHE["actions"] = generate_actions(df, CACHE["insights"])

        # Extract anomalies for cache
        anomalies_df = df[df["is_anomaly"]].copy()
        CACHE["anomalies"] = anomalies_df.to_dict("records")

        # Calculate processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)

        # Store metadata
        CACHE["metadata"] = {
            "upload_time": start_time,
            "transaction_count": len(df),
            "date_range": {
                "start": str(df["date"].min()),
                "end": str(df["date"].max())
            },
            "processing_time_ms": processing_time,
            "file_hash": file_hash
        }

        return {
            "transaction_count": len(df),
            "date_range": CACHE["metadata"]["date_range"],
            "processing_time_ms": processing_time
        }

    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="No valid transactions found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.get("/dashboard")
async def get_dashboard():
    """
    T032: Get complete dashboard data including summary, insights, anomalies, and actions
    """
    if CACHE["df"] is None:
        raise HTTPException(
            status_code=400,
            detail="No data uploaded. Please upload a CSV file first."
        )

    df = CACHE["df"]

    # Calculate summary
    total_spend = df["amount_float"].sum()
    anomaly_count = len(df[df["is_anomaly"]])
    anomaly_percentage = (anomaly_count / len(df)) * 100 if len(df) > 0 else 0

    category_breakdown = df.groupby("category")["amount_float"].sum().to_dict()

    top_vendors = (
        df.groupby("vendor_normalized")
        .agg({"amount_float": ["sum", "count"]})
        .reset_index()
    )
    top_vendors.columns = ["vendor", "amount", "count"]
    top_vendors = top_vendors.sort_values("amount", ascending=False).head(10)
    top_vendors_list = top_vendors.to_dict("records")

    high_risk_count = len(df[df["anomaly_score"] >= 8])

    summary = {
        "total_spend": total_spend,
        "anomaly_count": anomaly_count,
        "anomaly_percentage": round(anomaly_percentage, 1),
        "category_breakdown": category_breakdown,
        "top_vendors": top_vendors_list,
        "categories_tracked": len(category_breakdown),
        "high_risk_count": high_risk_count
    }

    CACHE["summary"] = summary

    return {
        "summary": summary,
        "insights": CACHE["insights"],
        "anomalies": CACHE["anomalies"],
        "actions": CACHE["actions"]
    }


@app.get("/transactions")
async def get_transactions(
    category: Optional[str] = None,
    anomaly: Optional[bool] = None,
    page: int = 1,
    limit: int = 50
):
    """T048: Get paginated transactions with filters"""
    if CACHE["df"] is None:
        raise HTTPException(
            status_code=400,
            detail="No data uploaded. Please upload a CSV file first."
        )

    df = CACHE["df"].copy()

    # Apply filters
    if category:
        df = df[df["category"] == category]

    if anomaly is not None:
        df = df[df["is_anomaly"] == anomaly]

    # Calculate pagination
    total_count = len(df)
    total_pages = (total_count + limit - 1) // limit  # Ceiling division

    # Get page data
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    page_df = df.iloc[start_idx:end_idx]

    # Convert to records
    transactions = page_df.to_dict("records")

    # Convert date to string for JSON serialization
    for txn in transactions:
        if "date" in txn and pd.notna(txn["date"]):
            txn["date"] = txn["date"].strftime("%Y-%m-%d")

    return {
        "transactions": transactions,
        "total_pages": total_pages,
        "current_page": page,
        "total_count": total_count
    }


@app.get("/actions")
async def get_actions():
    """T042: Get all recommended actions"""
    if CACHE["df"] is None:
        raise HTTPException(
            status_code=400,
            detail="No data uploaded. Please upload a CSV file first."
        )

    return {"actions": CACHE["actions"]}


@app.post("/actions/{action_id}/execute")
async def execute_action(action_id: str):
    """
    T043: Execute an auto-executable action
    T044: Simulate action execution by updating transaction tags
    """
    # Find action
    action = next((a for a in CACHE["actions"] if a["id"] == action_id), None)

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if action["status"] == "executed":
        raise HTTPException(status_code=400, detail="Action already executed")

    if action["status"] == "dismissed":
        raise HTTPException(status_code=400, detail="Action has been dismissed")

    if not action["auto_executable"]:
        raise HTTPException(status_code=400, detail="Action requires manual approval")

    # Execute action (simulate by tagging transaction)
    if action["type"] == "review" and action["target_type"] == "transaction":
        df = CACHE["df"]
        txn_id = action["target"]

        # Add tag to transaction
        if "tags" not in df.columns:
            df["tags"] = ""

        df.loc[df["id"] == txn_id, "tags"] = "NEEDS_REVIEW"
        CACHE["df"] = df

        # Update action status
        action["status"] = "executed"

        return {
            "status": "executed",
            "message": "Transaction flagged for review",
            "action_taken": "Added 'NEEDS_REVIEW' tag"
        }

    return {
        "status": "executed",
        "message": "Action executed successfully"
    }


@app.post("/actions/{action_id}/dismiss")
async def dismiss_action(action_id: str):
    """T045: Dismiss an action"""
    # Find action
    action = next((a for a in CACHE["actions"] if a["id"] == action_id), None)

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    # Update action status
    action["status"] = "dismissed"

    return {"status": "dismissed"}


# Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Catch-all error handler for processing crashes"""
    return {
        "error": "Processing failed - please try again or contact support",
        "detail": str(exc)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

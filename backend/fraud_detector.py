"""
Invoice Fraud Detection System
Detects altered invoices, duplicate submissions, and suspicious patterns
"""

from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
import re
import hashlib


@dataclass
class FraudAlert:
    """Represents a fraud detection alert"""
    alert_id: str
    invoice_id: str
    alert_type: str
    severity: str  # low, medium, high, critical
    confidence: float
    description: str
    evidence: List[str]
    recommended_action: str


class FraudDetector:
    """
    Intelligent fraud detection for invoices
    Detects alterations, duplicates, and suspicious patterns
    """

    def __init__(self):
        # Fraud detection thresholds
        self.duplicate_similarity_threshold = 0.95
        self.amount_manipulation_threshold = 0.15  # 15% change
        self.suspicious_round_amount_threshold = 1000  # Round amounts over $1000

        # Pattern tracking
        self.vendor_history = {}
        self.amount_patterns = {}

    def analyze_invoice(
        self,
        invoice: Dict,
        historical_invoices: List[Dict],
        transactions: Optional[pd.DataFrame] = None
    ) -> Dict[str, any]:
        """
        Comprehensive fraud analysis of an invoice

        Args:
            invoice: Invoice data to analyze
            historical_invoices: Previous invoices for pattern analysis
            transactions: Bank transactions for cross-validation

        Returns:
            Dictionary with fraud alerts and risk score
        """
        alerts = []

        # 1. Duplicate detection
        duplicate_alerts = self._detect_duplicates(invoice, historical_invoices)
        alerts.extend(duplicate_alerts)

        # 2. Amount manipulation detection
        amount_alerts = self._detect_amount_manipulation(invoice)
        alerts.extend(amount_alerts)

        # 3. Vendor verification
        vendor_alerts = self._verify_vendor(invoice, historical_invoices)
        alerts.extend(vendor_alerts)

        # 4. Pattern anomalies
        pattern_alerts = self._detect_pattern_anomalies(invoice, historical_invoices)
        alerts.extend(pattern_alerts)

        # 5. Document integrity checks
        integrity_alerts = self._check_document_integrity(invoice)
        alerts.extend(integrity_alerts)

        # 6. Cross-validation with transactions
        if transactions is not None:
            validation_alerts = self._cross_validate_with_transactions(invoice, transactions)
            alerts.extend(validation_alerts)

        # Calculate overall risk score
        risk_score = self._calculate_risk_score(alerts)

        return {
            'invoice_id': invoice.get('file_hash', 'unknown'),
            'risk_score': risk_score,
            'risk_level': self._get_risk_level(risk_score),
            'alerts': [self._alert_to_dict(a) for a in alerts],
            'alert_count': len(alerts),
            'critical_alerts': len([a for a in alerts if a.severity == 'critical']),
            'high_alerts': len([a for a in alerts if a.severity == 'high']),
            'recommendation': self._get_recommendation(risk_score, alerts)
        }

    def _detect_duplicates(
        self,
        invoice: Dict,
        historical_invoices: List[Dict]
    ) -> List[FraudAlert]:
        """Detect duplicate or near-duplicate invoices"""
        alerts = []

        invoice_number = invoice.get('invoice_number')
        invoice_amount = invoice.get('amounts', {}).get('total')
        invoice_vendor = invoice.get('vendor', '').lower()
        invoice_date = invoice.get('date')

        for hist in historical_invoices:
            hist_number = hist.get('invoice_number')
            hist_amount = hist.get('amounts', {}).get('total')
            hist_vendor = hist.get('vendor', '').lower()
            hist_date = hist.get('date')

            # Exact duplicate (same invoice number and vendor)
            if invoice_number and hist_number:
                if invoice_number == hist_number and invoice_vendor == hist_vendor:
                    alerts.append(FraudAlert(
                        alert_id=self._generate_alert_id(),
                        invoice_id=invoice.get('file_hash', 'unknown'),
                        alert_type='duplicate_invoice',
                        severity='critical',
                        confidence=1.0,
                        description=f'Duplicate invoice number: {invoice_number}',
                        evidence=[
                            f'Invoice #{invoice_number} already submitted',
                            f'Previous submission: {hist_date}',
                            f'Vendor: {invoice_vendor}'
                        ],
                        recommended_action='REJECT - Duplicate submission detected'
                    ))

            # Near duplicate (same vendor, amount, similar date)
            if invoice_amount and hist_amount:
                amount_match = abs(invoice_amount - hist_amount) < 0.01
                vendor_match = invoice_vendor == hist_vendor

                if amount_match and vendor_match and invoice_date and hist_date:
                    try:
                        date_diff = abs((pd.to_datetime(invoice_date) - pd.to_datetime(hist_date)).days)
                        if date_diff <= 7:
                            alerts.append(FraudAlert(
                                alert_id=self._generate_alert_id(),
                                invoice_id=invoice.get('file_hash', 'unknown'),
                                alert_type='near_duplicate',
                                severity='high',
                                confidence=0.85,
                                description=f'Possible duplicate: same vendor, amount, and date range',
                                evidence=[
                                    f'Vendor: {invoice_vendor}',
                                    f'Amount: ${invoice_amount:.2f}',
                                    f'Date difference: {date_diff} days'
                                ],
                                recommended_action='REVIEW - Verify if legitimate repeat purchase'
                            ))
                    except:
                        pass

        return alerts

    def _detect_amount_manipulation(self, invoice: Dict) -> List[FraudAlert]:
        """Detect suspicious amount patterns"""
        alerts = []

        amounts = invoice.get('amounts', {})
        total = amounts.get('total') or 0
        subtotal = amounts.get('subtotal')
        tax = amounts.get('tax')
        line_items = invoice.get('line_items', [])

        # Check if amounts are suspiciously round
        if total and total >= self.suspicious_round_amount_threshold:
            if total % 100 == 0 or total % 1000 == 0:
                alerts.append(FraudAlert(
                    alert_id=self._generate_alert_id(),
                    invoice_id=invoice.get('file_hash', 'unknown'),
                    alert_type='suspicious_round_amount',
                    severity='medium',
                    confidence=0.6,
                    description=f'Suspiciously round amount: ${total:.2f}',
                    evidence=[
                        f'Total is exact multiple of ${100 if total % 100 == 0 else 1000}',
                        'Large round amounts may indicate fabrication'
                    ],
                    recommended_action='REVIEW - Verify invoice authenticity'
                ))

        # Validate subtotal + tax = total
        if subtotal and tax and total:
            calculated_total = subtotal + tax
            diff = abs(calculated_total - total)
            diff_pct = diff / total if total > 0 else 0

            if diff_pct > 0.02:  # More than 2% difference
                alerts.append(FraudAlert(
                    alert_id=self._generate_alert_id(),
                    invoice_id=invoice.get('file_hash', 'unknown'),
                    alert_type='calculation_mismatch',
                    severity='high',
                    confidence=0.9,
                    description='Invoice calculation error detected',
                    evidence=[
                        f'Subtotal: ${subtotal:.2f}',
                        f'Tax: ${tax:.2f}',
                        f'Stated Total: ${total:.2f}',
                        f'Calculated Total: ${calculated_total:.2f}',
                        f'Difference: ${diff:.2f} ({diff_pct:.1%})'
                    ],
                    recommended_action='REJECT - Mathematical error or manipulation'
                ))

        # Validate line items sum to subtotal
        if line_items and subtotal:
            line_items_total = sum(item.get('total', 0) for item in line_items)
            diff = abs(line_items_total - subtotal)
            diff_pct = diff / subtotal if subtotal > 0 else 0

            if diff_pct > 0.05:  # More than 5% difference
                alerts.append(FraudAlert(
                    alert_id=self._generate_alert_id(),
                    invoice_id=invoice.get('file_hash', 'unknown'),
                    alert_type='line_items_mismatch',
                    severity='high',
                    confidence=0.85,
                    description='Line items do not match subtotal',
                    evidence=[
                        f'Line items sum: ${line_items_total:.2f}',
                        f'Stated subtotal: ${subtotal:.2f}',
                        f'Difference: ${diff:.2f} ({diff_pct:.1%})'
                    ],
                    recommended_action='REVIEW - Verify line item calculations'
                ))

        return alerts

    def _verify_vendor(
        self,
        invoice: Dict,
        historical_invoices: List[Dict]
    ) -> List[FraudAlert]:
        """Verify vendor legitimacy and consistency"""
        alerts = []

        vendor = invoice.get('vendor', '').lower()
        invoice_number = invoice.get('invoice_number', '')

        # Check for suspicious vendor names
        suspicious_patterns = [
            r'test',
            r'sample',
            r'example',
            r'dummy',
            r'fake',
            r'xxx',
            r'abc\s*company',
            r'vendor\s*\d+'
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, vendor, re.IGNORECASE):
                alerts.append(FraudAlert(
                    alert_id=self._generate_alert_id(),
                    invoice_id=invoice.get('file_hash', 'unknown'),
                    alert_type='suspicious_vendor_name',
                    severity='high',
                    confidence=0.8,
                    description=f'Suspicious vendor name pattern detected',
                    evidence=[
                        f'Vendor: {vendor}',
                        f'Matches pattern: {pattern}'
                    ],
                    recommended_action='REVIEW - Verify vendor legitimacy'
                ))

        # Check invoice number format consistency for this vendor
        vendor_invoices = [
            inv for inv in historical_invoices
            if inv.get('vendor', '').lower() == vendor
        ]

        if len(vendor_invoices) >= 3:
            # Analyze invoice number patterns
            invoice_numbers = [inv.get('invoice_number', '') for inv in vendor_invoices if inv.get('invoice_number')]

            if invoice_numbers and invoice_number:
                # Check if format is consistent
                current_format = self._extract_invoice_format(invoice_number)
                historical_formats = [self._extract_invoice_format(num) for num in invoice_numbers]

                if current_format not in historical_formats:
                    alerts.append(FraudAlert(
                        alert_id=self._generate_alert_id(),
                        invoice_id=invoice.get('file_hash', 'unknown'),
                        alert_type='inconsistent_invoice_format',
                        severity='medium',
                        confidence=0.7,
                        description='Invoice number format differs from vendor history',
                        evidence=[
                            f'Current format: {current_format}',
                            f'Historical formats: {", ".join(set(historical_formats))}'
                        ],
                        recommended_action='REVIEW - Verify invoice authenticity'
                    ))

        return alerts

    def _detect_pattern_anomalies(
        self,
        invoice: Dict,
        historical_invoices: List[Dict]
    ) -> List[FraudAlert]:
        """Detect anomalies in spending patterns"""
        alerts = []

        vendor = invoice.get('vendor', '').lower()
        amount = invoice.get('amounts', {}).get('total', 0)

        # Get historical amounts for this vendor
        vendor_amounts = [
            inv.get('amounts', {}).get('total', 0)
            for inv in historical_invoices
            if inv.get('vendor', '').lower() == vendor
        ]

        if len(vendor_amounts) >= 3:
            avg_amount = np.mean(vendor_amounts)
            std_amount = np.std(vendor_amounts)

            # Check if current amount is anomalous
            if std_amount > 0:
                z_score = abs((amount - avg_amount) / std_amount)

                if z_score > 3:  # More than 3 standard deviations
                    alerts.append(FraudAlert(
                        alert_id=self._generate_alert_id(),
                        invoice_id=invoice.get('file_hash', 'unknown'),
                        alert_type='amount_anomaly',
                        severity='medium',
                        confidence=0.75,
                        description=f'Amount significantly differs from vendor history',
                        evidence=[
                            f'Current amount: ${amount:.2f}',
                            f'Historical average: ${avg_amount:.2f}',
                            f'Standard deviation: ${std_amount:.2f}',
                            f'Z-score: {z_score:.2f}'
                        ],
                        recommended_action='REVIEW - Verify unusual amount'
                    ))

        return alerts

    def _check_document_integrity(self, invoice: Dict) -> List[FraudAlert]:
        """Check for signs of document manipulation"""
        alerts = []

        confidence = invoice.get('confidence', 1.0)

        # Low OCR confidence may indicate poor quality or altered document
        if confidence < 0.5:
            alerts.append(FraudAlert(
                alert_id=self._generate_alert_id(),
                invoice_id=invoice.get('file_hash', 'unknown'),
                alert_type='low_ocr_confidence',
                severity='medium',
                confidence=0.6,
                description='Low OCR extraction confidence',
                evidence=[
                    f'OCR confidence: {confidence:.1%}',
                    'May indicate poor scan quality or document alteration'
                ],
                recommended_action='REVIEW - Request original document'
            ))

        # Check for missing critical fields
        missing_fields = []
        if not invoice.get('vendor'):
            missing_fields.append('vendor')
        if not invoice.get('invoice_number'):
            missing_fields.append('invoice_number')
        if not invoice.get('date'):
            missing_fields.append('date')
        if not invoice.get('amounts', {}).get('total'):
            missing_fields.append('total_amount')

        if missing_fields:
            alerts.append(FraudAlert(
                alert_id=self._generate_alert_id(),
                invoice_id=invoice.get('file_hash', 'unknown'),
                alert_type='missing_critical_fields',
                severity='high',
                confidence=0.9,
                description='Critical invoice fields missing',
                evidence=[
                    f'Missing fields: {", ".join(missing_fields)}',
                    'Incomplete invoices may be fraudulent'
                ],
                recommended_action='REJECT - Request complete invoice'
            ))

        return alerts

    def _cross_validate_with_transactions(
        self,
        invoice: Dict,
        transactions: pd.DataFrame
    ) -> List[FraudAlert]:
        """Cross-validate invoice against bank transactions"""
        alerts = []

        invoice_amount = invoice.get('amounts', {}).get('total')
        invoice_vendor = invoice.get('vendor', '').lower()
        invoice_date = invoice.get('date')

        if not invoice_amount or not invoice_date:
            return alerts

        try:
            invoice_dt = pd.to_datetime(invoice_date)

            # Look for matching transaction within 30 days
            date_min = invoice_dt - timedelta(days=30)
            date_max = invoice_dt + timedelta(days=30)

            matching_txns = transactions[
                (transactions['date'] >= date_min) &
                (transactions['date'] <= date_max) &
                (transactions['vendor'].str.lower().str.contains(invoice_vendor[:10], na=False))
            ]

            if matching_txns.empty:
                alerts.append(FraudAlert(
                    alert_id=self._generate_alert_id(),
                    invoice_id=invoice.get('file_hash', 'unknown'),
                    alert_type='no_matching_transaction',
                    severity='high',
                    confidence=0.8,
                    description='No matching bank transaction found',
                    evidence=[
                        f'Invoice amount: ${invoice_amount:.2f}',
                        f'Invoice date: {invoice_date}',
                        f'Vendor: {invoice_vendor}',
                        'No transaction found within 30 days'
                    ],
                    recommended_action='REVIEW - Verify payment was made'
                ))

        except:
            pass

        return alerts

    def _calculate_risk_score(self, alerts: List[FraudAlert]) -> float:
        """Calculate overall risk score (0-100)"""
        if not alerts:
            return 0.0

        # Weight by severity
        severity_weights = {
            'critical': 40,
            'high': 25,
            'medium': 10,
            'low': 5
        }

        total_score = 0.0
        for alert in alerts:
            weight = severity_weights.get(alert.severity, 5)
            total_score += weight * alert.confidence

        # Cap at 100
        return min(total_score, 100.0)

    def _get_risk_level(self, risk_score: float) -> str:
        """Convert risk score to risk level"""
        if risk_score >= 75:
            return 'critical'
        elif risk_score >= 50:
            return 'high'
        elif risk_score >= 25:
            return 'medium'
        else:
            return 'low'

    def _get_recommendation(self, risk_score: float, alerts: List[FraudAlert]) -> str:
        """Get overall recommendation"""
        if risk_score >= 75:
            return 'REJECT - High fraud risk detected. Do not process this invoice.'
        elif risk_score >= 50:
            return 'HOLD - Significant concerns. Require manual review and verification.'
        elif risk_score >= 25:
            return 'REVIEW - Minor issues detected. Verify before processing.'
        else:
            return 'APPROVE - Low risk. Safe to process.'

    def _extract_invoice_format(self, invoice_number: str) -> str:
        """Extract format pattern from invoice number"""
        # Replace digits with 'N', letters with 'A'
        pattern = re.sub(r'\d', 'N', invoice_number)
        pattern = re.sub(r'[a-zA-Z]', 'A', pattern)
        return pattern

    def _generate_alert_id(self) -> str:
        """Generate unique alert ID"""
        return f"alert_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    def _alert_to_dict(self, alert: FraudAlert) -> Dict:
        """Convert FraudAlert to dictionary"""
        return {
            'alert_id': alert.alert_id,
            'invoice_id': alert.invoice_id,
            'alert_type': alert.alert_type,
            'severity': alert.severity,
            'confidence': alert.confidence,
            'description': alert.description,
            'evidence': alert.evidence,
            'recommended_action': alert.recommended_action
        }


if __name__ == "__main__":
    """Test fraud detection"""
    print("=" * 80)
    print("FRAUD DETECTION SYSTEM TEST")
    print("=" * 80)

    # Sample invoice
    invoice = {
        'file_hash': 'test001',
        'vendor': 'Test Company',
        'invoice_number': 'INV-001',
        'date': '2024-03-15',
        'amounts': {
            'total': 1000.00,
            'subtotal': 900.00,
            'tax': 100.00
        },
        'line_items': [
            {'description': 'Service', 'total': 900.00}
        ],
        'confidence': 0.95
    }

    historical = []
    transactions = pd.DataFrame()

    detector = FraudDetector()
    result = detector.analyze_invoice(invoice, historical, transactions)

    print(f"\nFraud Analysis Results:")
    print(f"  Risk Score: {result['risk_score']:.1f}/100")
    print(f"  Risk Level: {result['risk_level'].upper()}")
    print(f"  Total Alerts: {result['alert_count']}")
    print(f"  Recommendation: {result['recommendation']}")

    if result['alerts']:
        print(f"\nAlerts:")
        for alert in result['alerts']:
            print(f"  [{alert['severity'].upper()}] {alert['description']}")
            print(f"    Confidence: {alert['confidence']:.0%}")
            print(f"    Action: {alert['recommended_action']}")

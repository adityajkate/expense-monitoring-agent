"""
Invoice Matching System
Matches invoices to bank transactions, detects discrepancies, and flags missing invoices
"""

from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import pandas as pd
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class Match:
    """Represents a match between invoice and transaction"""
    invoice_id: str
    transaction_id: str
    match_score: float
    match_type: str  # exact, fuzzy, partial
    amount_match: bool
    vendor_match: bool
    date_match: bool
    discrepancies: List[str]


class InvoiceMatcher:
    """
    Intelligent invoice-to-transaction matching system
    Uses multiple matching strategies with confidence scoring
    """

    def __init__(self, date_tolerance_days: int = 7, amount_tolerance_pct: float = 0.02):
        """
        Initialize matcher

        Args:
            date_tolerance_days: Days before/after invoice date to search for transaction
            amount_tolerance_pct: Percentage tolerance for amount matching (2% default)
        """
        self.date_tolerance_days = date_tolerance_days
        self.amount_tolerance_pct = amount_tolerance_pct

    def match_invoices_to_transactions(
        self,
        invoices: List[Dict],
        transactions: pd.DataFrame
    ) -> Dict[str, any]:
        """
        Match all invoices to transactions

        Args:
            invoices: List of invoice data dictionaries
            transactions: DataFrame of bank transactions

        Returns:
            Dictionary with matches, unmatched invoices, unmatched transactions, discrepancies
        """
        matches = []
        unmatched_invoices = []
        matched_transaction_ids = set()

        # Process each invoice
        for invoice in invoices:
            match = self._find_best_match(invoice, transactions, matched_transaction_ids)

            if match:
                matches.append(match)
                matched_transaction_ids.add(match.transaction_id)
            else:
                unmatched_invoices.append({
                    'invoice_id': invoice.get('file_hash', 'unknown'),
                    'vendor': invoice.get('vendor'),
                    'amount': invoice.get('amounts', {}).get('total'),
                    'date': invoice.get('date'),
                    'reason': 'No matching transaction found'
                })

        # Find unmatched transactions (potential missing invoices)
        unmatched_transactions = self._find_unmatched_transactions(
            transactions,
            matched_transaction_ids
        )

        # Analyze discrepancies
        discrepancies = self._analyze_discrepancies(matches)

        return {
            'matches': [self._match_to_dict(m) for m in matches],
            'unmatched_invoices': unmatched_invoices,
            'unmatched_transactions': unmatched_transactions,
            'discrepancies': discrepancies,
            'summary': {
                'total_invoices': len(invoices),
                'total_transactions': len(transactions),
                'matched': len(matches),
                'unmatched_invoices': len(unmatched_invoices),
                'unmatched_transactions': len(unmatched_transactions),
                'discrepancies': len(discrepancies),
                'match_rate': len(matches) / len(invoices) if invoices else 0
            }
        }

    def _find_best_match(
        self,
        invoice: Dict,
        transactions: pd.DataFrame,
        already_matched: set
    ) -> Optional[Match]:
        """
        Find best matching transaction for an invoice

        Args:
            invoice: Invoice data
            transactions: All transactions
            already_matched: Set of already matched transaction IDs

        Returns:
            Best match or None
        """
        invoice_amount = invoice.get('amounts', {}).get('total')
        invoice_vendor = invoice.get('vendor', '').lower()
        invoice_date = invoice.get('date')

        if not invoice_amount or not invoice_date:
            return None

        # Parse invoice date
        try:
            invoice_dt = pd.to_datetime(invoice_date)
        except:
            return None

        # Filter candidates by date range
        date_min = invoice_dt - timedelta(days=self.date_tolerance_days)
        date_max = invoice_dt + timedelta(days=self.date_tolerance_days)

        candidates = transactions[
            (transactions['date'] >= date_min) &
            (transactions['date'] <= date_max) &
            (~transactions['id'].isin(already_matched))
        ].copy()

        if candidates.empty:
            return None

        # Score each candidate
        best_match = None
        best_score = 0.0

        for _, txn in candidates.iterrows():
            score, match_details = self._calculate_match_score(
                invoice,
                txn,
                invoice_dt
            )

            if score > best_score and score >= 0.6:  # Minimum 60% match
                best_score = score
                best_match = Match(
                    invoice_id=invoice.get('file_hash', 'unknown'),
                    transaction_id=txn['id'],
                    match_score=score,
                    match_type=match_details['type'],
                    amount_match=match_details['amount_match'],
                    vendor_match=match_details['vendor_match'],
                    date_match=match_details['date_match'],
                    discrepancies=match_details['discrepancies']
                )

        return best_match

    def _calculate_match_score(
        self,
        invoice: Dict,
        transaction: pd.Series,
        invoice_dt: datetime
    ) -> Tuple[float, Dict]:
        """
        Calculate match score between invoice and transaction

        Returns:
            Tuple of (score, match_details)
        """
        score = 0.0
        discrepancies = []

        # Amount matching (40% weight)
        invoice_amount = invoice.get('amounts', {}).get('total', 0)
        txn_amount = transaction['amount']
        amount_diff = abs(invoice_amount - txn_amount)
        amount_diff_pct = amount_diff / invoice_amount if invoice_amount > 0 else 1.0

        amount_match = amount_diff_pct <= self.amount_tolerance_pct

        if amount_match:
            score += 0.4
        elif amount_diff_pct <= 0.05:  # Within 5%
            score += 0.3
            discrepancies.append(f"Amount mismatch: Invoice ${invoice_amount:.2f} vs Transaction ${txn_amount:.2f}")
        elif amount_diff_pct <= 0.10:  # Within 10%
            score += 0.2
            discrepancies.append(f"Significant amount mismatch: Invoice ${invoice_amount:.2f} vs Transaction ${txn_amount:.2f}")
        else:
            discrepancies.append(f"Large amount mismatch: Invoice ${invoice_amount:.2f} vs Transaction ${txn_amount:.2f}")

        # Vendor matching (40% weight)
        invoice_vendor = invoice.get('vendor', '').lower()
        txn_vendor = str(transaction['vendor']).lower()

        vendor_similarity = self._string_similarity(invoice_vendor, txn_vendor)
        vendor_match = vendor_similarity >= 0.8

        if vendor_match:
            score += 0.4
        elif vendor_similarity >= 0.6:
            score += 0.3
            discrepancies.append(f"Vendor name variation: Invoice '{invoice_vendor}' vs Transaction '{txn_vendor}'")
        elif vendor_similarity >= 0.4:
            score += 0.2
            discrepancies.append(f"Vendor mismatch: Invoice '{invoice_vendor}' vs Transaction '{txn_vendor}'")
        else:
            discrepancies.append(f"Vendor mismatch: Invoice '{invoice_vendor}' vs Transaction '{txn_vendor}'")

        # Date matching (20% weight)
        txn_dt = pd.to_datetime(transaction['date'])
        date_diff_days = abs((invoice_dt - txn_dt).days)

        date_match = date_diff_days <= 1

        if date_match:
            score += 0.2
        elif date_diff_days <= 3:
            score += 0.15
        elif date_diff_days <= self.date_tolerance_days:
            score += 0.1
            discrepancies.append(f"Date difference: {date_diff_days} days")
        else:
            discrepancies.append(f"Large date difference: {date_diff_days} days")

        # Determine match type
        if score >= 0.95:
            match_type = "exact"
        elif score >= 0.75:
            match_type = "fuzzy"
        else:
            match_type = "partial"

        return score, {
            'type': match_type,
            'amount_match': amount_match,
            'vendor_match': vendor_match,
            'date_match': date_match,
            'discrepancies': discrepancies
        }

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using SequenceMatcher"""
        return SequenceMatcher(None, s1, s2).ratio()

    def _find_unmatched_transactions(
        self,
        transactions: pd.DataFrame,
        matched_ids: set
    ) -> List[Dict]:
        """Find transactions without matching invoices"""
        unmatched = transactions[~transactions['id'].isin(matched_ids)]

        # Filter for transactions that likely need invoices
        # (e.g., large amounts, certain categories)
        unmatched_list = []

        for _, txn in unmatched.iterrows():
            # Flag transactions over $500 or in certain categories
            needs_invoice = (
                txn['amount'] > 500 or
                txn.get('category') in ['Cloud', 'Software', 'Office', 'Operations']
            )

            if needs_invoice:
                unmatched_list.append({
                    'transaction_id': txn['id'],
                    'vendor': txn['vendor'],
                    'amount': float(txn['amount']),
                    'date': str(txn['date']),
                    'category': txn.get('category', 'Unknown'),
                    'reason': 'Missing invoice - transaction over $500 or requires documentation'
                })

        return unmatched_list

    def _analyze_discrepancies(self, matches: List[Match]) -> List[Dict]:
        """Analyze matches for discrepancies"""
        discrepancies = []

        for match in matches:
            if match.discrepancies:
                discrepancies.append({
                    'invoice_id': match.invoice_id,
                    'transaction_id': match.transaction_id,
                    'match_score': match.match_score,
                    'issues': match.discrepancies,
                    'severity': self._calculate_severity(match)
                })

        return discrepancies

    def _calculate_severity(self, match: Match) -> str:
        """Calculate severity of discrepancies"""
        if match.match_score >= 0.9:
            return "low"
        elif match.match_score >= 0.75:
            return "medium"
        else:
            return "high"

    def _match_to_dict(self, match: Match) -> Dict:
        """Convert Match object to dictionary"""
        return {
            'invoice_id': match.invoice_id,
            'transaction_id': match.transaction_id,
            'match_score': match.match_score,
            'match_type': match.match_type,
            'amount_match': match.amount_match,
            'vendor_match': match.vendor_match,
            'date_match': match.date_match,
            'discrepancies': match.discrepancies
        }


if __name__ == "__main__":
    """Test invoice matching"""
    print("=" * 80)
    print("INVOICE MATCHING SYSTEM TEST")
    print("=" * 80)

    # Sample data
    invoices = [
        {
            'file_hash': 'inv001',
            'vendor': 'Amazon Web Services',
            'amounts': {'total': 1500.00},
            'date': '2024-03-15'
        },
        {
            'file_hash': 'inv002',
            'vendor': 'Microsoft',
            'amounts': {'total': 299.00},
            'date': '2024-03-20'
        }
    ]

    transactions = pd.DataFrame([
        {'id': 'txn001', 'vendor': 'aws', 'amount': 1500.00, 'date': '2024-03-16'},
        {'id': 'txn002', 'vendor': 'microsoft', 'amount': 299.00, 'date': '2024-03-20'},
        {'id': 'txn003', 'vendor': 'google', 'amount': 800.00, 'date': '2024-03-18'},
    ])
    transactions['date'] = pd.to_datetime(transactions['date'])

    matcher = InvoiceMatcher()
    results = matcher.match_invoices_to_transactions(invoices, transactions)

    print(f"\nMatching Results:")
    print(f"  Total Invoices: {results['summary']['total_invoices']}")
    print(f"  Total Transactions: {results['summary']['total_transactions']}")
    print(f"  Matched: {results['summary']['matched']}")
    print(f"  Match Rate: {results['summary']['match_rate']:.1%}")
    print(f"  Unmatched Invoices: {results['summary']['unmatched_invoices']}")
    print(f"  Unmatched Transactions: {results['summary']['unmatched_transactions']}")
    print(f"  Discrepancies: {results['summary']['discrepancies']}")

    print("\nMatches:")
    for match in results['matches']:
        print(f"  {match['invoice_id']} <-> {match['transaction_id']}")
        print(f"    Score: {match['match_score']:.2%} ({match['match_type']})")
        if match['discrepancies']:
            print(f"    Issues: {', '.join(match['discrepancies'])}")

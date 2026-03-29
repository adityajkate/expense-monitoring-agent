"""
Intelligent Invoice Parser with Layout Understanding
Uses spatial analysis and pattern recognition to understand invoice structure
"""

import re
from typing import Dict, List, Tuple, Optional
import numpy as np
from dataclasses import dataclass
from collections import defaultdict
from dateutil import parser as date_parser


@dataclass
class BoundingBox:
    """Represents text location on page"""
    x: float
    y: float
    width: float
    height: float
    text: str
    confidence: float


@dataclass
class LineItem:
    """Represents a product/service line item"""
    description: str
    quantity: Optional[float]
    unit_price: Optional[float]
    total_price: float
    confidence: float
    raw_text: str


class IntelligentInvoiceParser:
    """
    Smart invoice parser that understands document structure
    Uses spatial analysis, pattern recognition, and heuristics
    """

    def __init__(self):
        # Common column headers for line items
        self.quantity_headers = ['qty', 'quantity', 'qnty', 'units', 'count', '#']
        self.description_headers = ['description', 'item', 'product', 'service', 'details', 'particulars']
        self.price_headers = ['price', 'rate', 'unit price', 'amount', 'cost']
        self.total_headers = ['total', 'amount', 'sum', 'subtotal']

        # Currency symbols
        self.currency_symbols = ['$', '€', '£', '¥', '₹', 'USD', 'EUR', 'GBP']
        self.header_noise_patterns = [
            r'^---\s*page\b',
            r'^page\s+\d+',
            r'^invoice\b',
            r'^date\b',
            r'^bill\s+to\b',
            r'^ship\s+to\b',
            r'^customer\b',
            r'^subtotal\b',
            r'^tax\b',
            r'^total\b',
        ]

    def parse_invoice_with_layout(self, text: str, ocr_data: Optional[Dict] = None) -> Dict:
        """
        Parse invoice understanding its layout structure

        Args:
            text: Raw OCR text
            ocr_data: Optional OCR data with bounding boxes (from pytesseract.image_to_data)

        Returns:
            Structured invoice data
        """
        # Split into lines
        lines = [
            line.strip() for line in text.split('\n')
            if line.strip() and not re.match(r'^---\s*page\s+\d+\s*---$', line.strip(), re.IGNORECASE)
        ]

        # Identify sections
        sections = self._identify_sections(lines)

        # Extract header information (vendor, invoice #, date)
        header_info = self._extract_header_info(sections.get('header', []))

        # Extract line items (products/services)
        line_items = self._extract_line_items_smart(sections.get('items', []))

        # Extract totals
        totals = self._extract_totals(sections.get('footer', []))

        # Validate and cross-check
        validated_items = self._validate_line_items(line_items, totals)

        return {
            'vendor': header_info.get('vendor'),
            'invoice_number': header_info.get('invoice_number'),
            'date': header_info.get('date'),
            'line_items': validated_items,
            'subtotal': totals.get('subtotal'),
            'tax': totals.get('tax'),
            'total': totals.get('total'),
            'confidence': self._calculate_confidence(header_info, validated_items, totals)
        }

    def _identify_sections(self, lines: List[str]) -> Dict[str, List[str]]:
        """
        Identify different sections of invoice (header, items, footer)
        Improved to detect table headers and structure
        """
        sections = {
            'header': [],
            'items': [],
            'footer': []
        }

        current_section = 'header'
        item_section_started = False

        for i, line in enumerate(lines):
            line_lower = line.lower()

            # Detect start of line items section
            # Look for table headers like "Description | Qty | Price | Total"
            if any(header in line_lower for header in self.description_headers + self.quantity_headers):
                current_section = 'items'
                item_section_started = True
                continue

            # Also detect table structure by looking for multiple column-like words
            if not item_section_started and i < 20:  # Check first 20 lines
                # Count potential column headers
                column_indicators = ['description', 'item', 'qty', 'quantity', 'price', 'amount', 'total']
                matches = sum(1 for indicator in column_indicators if indicator in line_lower)
                if matches >= 3:  # If 3+ column headers found
                    current_section = 'items'
                    item_section_started = True
                    continue

            # Detect end of line items (totals section)
            if item_section_started and any(keyword in line_lower for keyword in ['subtotal', 'total', 'tax', 'amount due']):
                current_section = 'footer'

            sections[current_section].append(line)

        return sections

    def _extract_header_info(self, header_lines: List[str]) -> Dict:
        """Extract vendor, invoice number, date from header"""
        info = {}

        # Vendor is usually in first few lines
        for line in header_lines:
            if self._is_header_noise(line):
                continue
            if len(line) < 4:
                continue
            info['vendor'] = line
            break

        # Invoice number patterns
        invoice_patterns = [
            r'(?:invoice|invoic[eos]|inv)\s*(?:no|number|#)?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{2,})',
            r'(?:reference|ref|doc(?:ument)?|bill)\s*(?:no|number|#)?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{2,})',
            r'bill\s*(?:no|#)?\s*:?\s*([A-Z0-9-]+)',
        ]

        for line in header_lines:
            for pattern in invoice_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    info['invoice_number'] = match.group(1)
                    break

        # Date patterns
        date_patterns = [
            r'date\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4})',
            r'((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4})',
        ]

        for line in header_lines:
            for pattern in date_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    info['date'] = self._normalize_date(match.group(1))
                    break

        return info

    def _extract_line_items_smart(self, item_lines: List[str]) -> List[LineItem]:
        """
        Intelligently extract line items with products and prices
        Handles various invoice formats
        """
        line_items = []

        # Pattern 1: Description ... Qty ... Price ... Total
        # Pattern 2: Description ... Total (no qty/price breakdown)
        # Pattern 3: Qty Description Price Total

        for line in item_lines:
            # Skip header lines
            if any(header in line.lower() for header in self.description_headers + self.quantity_headers):
                continue

            if self._is_non_item_line(line):
                continue

            # Skip empty or very short lines
            if len(line.strip()) < 3:
                continue

            # Try to parse line item
            item = self._parse_line_item(line)
            if item:
                line_items.append(item)

        return line_items

    def _parse_line_item(self, line: str) -> Optional[LineItem]:
        """
        Parse a single line item
        Handles multiple formats
        """
        # Extract all numbers from line
        numbers = self._extract_numbers(line)

        if not numbers:
            return None

        # Remove numbers from line to get description
        description = line
        for num_str in re.findall(r'[\d,]+\.?\d*', line):
            description = description.replace(num_str, '', 1)

        # Clean description
        description = re.sub(r'\s+', ' ', description).strip()
        description = re.sub(r'^[^\w]+|[^\w]+$', '', description)  # Remove leading/trailing non-word chars

        if not description or len(description) < 2:
            return None

        # Determine which numbers are qty, price, total
        qty, unit_price, total = self._identify_number_roles(numbers, line)

        # Total is required
        if total is None:
            total = numbers[-1]  # Last number is usually total

        if qty and unit_price and total:
            calculated_total = round(qty * unit_price, 2)
            if total > 0 and abs(calculated_total - total) / total < 0.05:
                total = calculated_total

        # Calculate confidence
        confidence = self._calculate_item_confidence(description, qty, unit_price, total, line)

        return LineItem(
            description=description,
            quantity=qty,
            unit_price=unit_price,
            total_price=total,
            confidence=confidence,
            raw_text=line
        )

    def _extract_numbers(self, text: str) -> List[float]:
        """Extract all numbers from text"""
        # Pattern for currency amounts: $1,234.56 or 1234.56
        pattern = r'\$?\s*([\d,]+\.?\d*)'
        matches = re.findall(pattern, text)

        numbers = []
        for match in matches:
            try:
                normalized = match.replace(',', '')
                if '.' not in normalized and len(normalized) >= 4 and (
                    '$' in text or re.search(r'\d+\.\d{2}', text)
                ):
                    num = float(normalized) / 100
                else:
                    num = float(normalized)
                if num > 0:  # Only positive numbers
                    numbers.append(num)
            except ValueError:
                continue

        return numbers

    def _identify_number_roles(self, numbers: List[float], line: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Identify which number is quantity, unit price, and total
        Uses improved heuristics and validation
        """
        if len(numbers) == 0:
            return None, None, None

        if len(numbers) == 1:
            # Only one number - it's the total
            return None, None, numbers[0]

        if len(numbers) == 2:
            # Two numbers - could be qty+total or price+total
            # Use position in line to help determine
            first_num, second_num = numbers[0], numbers[1]

            # If first number is small (< 100) and second is larger, likely qty+total
            if first_num < 100 and second_num > first_num * 2:
                return first_num, None, second_num
            # If first number is in reasonable price range, likely price+total
            elif first_num > 1 and first_num < second_num:
                return None, first_num, second_num
            else:
                # Default: second number is total
                return None, None, second_num

        if len(numbers) == 3:
            # Three numbers - likely qty, unit price, total
            qty, price, total = numbers[0], numbers[1], numbers[2]

            # Validate: qty * price ≈ total (within 5% instead of 10%)
            if qty > 0 and price > 0:
                calculated = qty * price
                diff_pct = abs(calculated - total) / total if total > 0 else 1.0

                if diff_pct < 0.05:  # Within 5%
                    return qty, price, total

            # Validation failed - maybe first number is item number, not qty
            # Try second and third as price and total
            if numbers[1] < numbers[2]:
                return None, numbers[1], numbers[2]

            # Last resort: just use last number as total
            return None, None, numbers[-1]

        if len(numbers) >= 4:
            # Multiple numbers - take last 3 and recurse
            return self._identify_number_roles(numbers[-3:], line)

        return None, None, numbers[-1]

    def _calculate_item_confidence(self, description: str, qty: Optional[float],
                                   unit_price: Optional[float], total: float, raw_line: str) -> float:
        """Calculate confidence score for line item"""
        confidence = 0.5  # Base confidence

        # Good description
        if len(description) > 5:
            confidence += 0.2

        # Has quantity
        if qty is not None:
            confidence += 0.1

        # Has unit price
        if unit_price is not None:
            confidence += 0.1

        # Qty * price ≈ total
        if qty and unit_price and total and total > 0:
            if abs(qty * unit_price - total) / total < 0.05:
                confidence += 0.2

        return min(confidence, 1.0)

    def _extract_totals(self, footer_lines: List[str]) -> Dict[str, float]:
        """Extract subtotal, tax, and total from footer"""
        totals = {}

        for line in footer_lines:
            line_lower = line.lower()
            numbers = self._extract_numbers(line)

            if not numbers:
                continue

            # Subtotal
            if 'subtotal' in line_lower and 'subtotal' not in totals:
                totals['subtotal'] = numbers[-1]

            # Tax
            elif any(keyword in line_lower for keyword in ['tax', 'vat', 'gst']) and 'tax' not in totals:
                totals['tax'] = numbers[-1]

            # Total
            elif any(keyword in line_lower for keyword in ['total', 'amount due', 'balance']) and 'total' not in totals:
                totals['total'] = numbers[-1]

        return totals

    def _validate_line_items(self, line_items: List[LineItem], totals: Dict[str, float]) -> List[Dict]:
        """
        Validate line items against totals with tighter tolerance
        Remove invalid items
        """
        validated = []

        # Calculate sum of line items
        items_total = sum(item.total_price for item in line_items)

        # Check if sum matches invoice total
        invoice_total = totals.get('total') or totals.get('subtotal')

        if invoice_total and invoice_total > 0:
            diff_pct = abs(items_total - invoice_total) / invoice_total

            # Tighter tolerance: 5% instead of 10%
            if diff_pct < 0.05:
                # Items sum matches total - include all items
                for item in line_items:
                    validated.append({
                        'description': item.description,
                        'quantity': item.quantity,
                        'unit_price': item.unit_price,
                        'total': item.total_price,
                        'confidence': item.confidence
                    })
            else:
                # Items don't match - filter by confidence
                # Only include items with confidence > 0.6
                for item in line_items:
                    if item.confidence > 0.6:
                        validated.append({
                            'description': item.description,
                            'quantity': item.quantity,
                            'unit_price': item.unit_price,
                            'total': item.total_price,
                            'confidence': item.confidence
                        })
        else:
            # No total to validate against - include all items with confidence > 0.5
            for item in line_items:
                if item.confidence > 0.5:
                    validated.append({
                        'description': item.description,
                        'quantity': item.quantity,
                        'unit_price': item.unit_price,
                        'total': item.total_price,
                        'confidence': item.confidence
                    })

        return validated

    def _calculate_confidence(self, header_info: Dict, line_items: List[Dict], totals: Dict) -> float:
        """
        Calculate overall extraction confidence with weighted scoring

        Weights:
        - Vendor: 25%
        - Total amount: 30%
        - Line items: 25%
        - Invoice number: 10%
        - Date: 10%
        """
        confidence_scores = {}

        # Vendor (25% weight)
        if header_info.get('vendor') and len(header_info['vendor']) > 3:
            confidence_scores['vendor'] = 0.9
        else:
            confidence_scores['vendor'] = 0.3

        # Total amount (30% weight)
        if totals.get('total') and totals['total'] > 0:
            # Boost confidence if subtotal + tax = total
            if totals.get('subtotal') and totals.get('tax'):
                calculated = totals['subtotal'] + totals['tax']
                diff_pct = abs(calculated - totals['total']) / totals['total']
                if diff_pct < 0.02:  # Within 2%
                    confidence_scores['total'] = 0.95
                else:
                    confidence_scores['total'] = 0.85
            else:
                confidence_scores['total'] = 0.9
        else:
            confidence_scores['total'] = 0.3

        # Line items (25% weight)
        if line_items:
            avg_item_confidence = np.mean([item['confidence'] for item in line_items])
            confidence_scores['line_items'] = avg_item_confidence
        else:
            confidence_scores['line_items'] = 0.4

        # Invoice number (10% weight)
        if header_info.get('invoice_number'):
            confidence_scores['invoice_number'] = 0.9
        else:
            confidence_scores['invoice_number'] = 0.5

        # Date (10% weight)
        if header_info.get('date'):
            confidence_scores['date'] = 0.9
        else:
            confidence_scores['date'] = 0.5

        # Calculate weighted average
        weights = {
            'vendor': 0.25,
            'total': 0.30,
            'line_items': 0.25,
            'invoice_number': 0.10,
            'date': 0.10
        }

        weighted_confidence = sum(
            confidence_scores.get(key, 0.3) * weight
            for key, weight in weights.items()
        )

        return float(weighted_confidence)

    def _normalize_date(self, raw_date: str) -> Optional[str]:
        """Normalize a detected date to ISO format when possible."""
        try:
            parsed = date_parser.parse(raw_date, fuzzy=True)
            return parsed.strftime('%Y-%m-%d')
        except Exception:
            return raw_date

    def _is_header_noise(self, line: str) -> bool:
        """Return True when a line is not a trustworthy header value."""
        line_lower = line.lower().strip()
        return any(re.match(pattern, line_lower, re.IGNORECASE) for pattern in self.header_noise_patterns)

    def _is_non_item_line(self, line: str) -> bool:
        """Return True when a line should not be treated as a line item."""
        line_lower = line.lower().strip()
        if self._is_header_noise(line):
            return True
        return bool(re.match(r'^(invoice|date|bill\s+to|customer|reference|ref)\b', line_lower))


# Integration with existing InvoiceOCR class
def enhance_invoice_extraction(ocr_text: str) -> Dict:
    """
    Enhanced invoice extraction with intelligent parsing
    """
    parser = IntelligentInvoiceParser()
    return parser.parse_invoice_with_layout(ocr_text)


if __name__ == "__main__":
    # Test with sample invoice text
    sample_invoice = """
    ACME Corporation
    123 Business St, City, State 12345

    Invoice #: INV-2024-001
    Date: March 28, 2024

    Bill To: Customer Name

    Description                          Qty    Price    Total
    ----------------------------------------------------------------
    Web Development Services             40     $150     $6,000
    Logo Design                          1      $500     $500
    Hosting (Annual)                     1      $200     $200
    Domain Registration                  1      $15      $15

    Subtotal:                                            $6,715
    Tax (8%):                                            $537.20
    Total:                                               $7,252.20
    """

    parser = IntelligentInvoiceParser()
    result = parser.parse_invoice_with_layout(sample_invoice)

    print("Parsed Invoice:")
    print(f"Vendor: {result['vendor']}")
    print(f"Invoice #: {result['invoice_number']}")
    print(f"Date: {result['date']}")
    print(f"\nLine Items ({len(result['line_items'])}):")
    for item in result['line_items']:
        print(f"  - {item['description']}: {item['quantity']} x ${item['unit_price']} = ${item['total']} (confidence: {item['confidence']:.0%})")
    print(f"\nSubtotal: ${result['subtotal']}")
    print(f"Tax: ${result['tax']}")
    print(f"Total: ${result['total']}")
    print(f"\nOverall Confidence: {result['confidence']:.0%}")

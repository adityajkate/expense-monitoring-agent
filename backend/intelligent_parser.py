"""
Intelligent Invoice Parser with Layout Understanding
Uses spatial analysis and pattern recognition to understand invoice structure
"""

import re
from typing import Dict, List, Tuple, Optional
import numpy as np
from dataclasses import dataclass
from collections import defaultdict


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
        lines = [line.strip() for line in text.split('\n') if line.strip()]

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
            if any(header in line_lower for header in self.description_headers + self.quantity_headers):
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
        if header_lines:
            # First non-empty line is often vendor
            info['vendor'] = header_lines[0] if header_lines else None

        # Invoice number patterns
        invoice_patterns = [
            r'invoice\s*(?:no|number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'inv\s*(?:no|#)?\s*:?\s*([A-Z0-9-]+)',
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
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}',
        ]

        for line in header_lines:
            for pattern in date_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    info['date'] = match.group(1)
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
                # Remove commas and convert
                num = float(match.replace(',', ''))
                if num > 0:  # Only positive numbers
                    numbers.append(num)
            except ValueError:
                continue

        return numbers

    def _identify_number_roles(self, numbers: List[float], line: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Identify which number is quantity, unit price, and total
        Uses heuristics and context
        """
        if len(numbers) == 0:
            return None, None, None

        if len(numbers) == 1:
            # Only one number - it's the total
            return None, None, numbers[0]

        if len(numbers) == 2:
            # Two numbers - could be qty+total or price+total
            # If first number is small (< 100), likely quantity
            if numbers[0] < 100 and numbers[1] > numbers[0]:
                return numbers[0], None, numbers[1]
            else:
                # Both are prices (unit price and total)
                return None, numbers[0], numbers[1]

        if len(numbers) == 3:
            # Three numbers - qty, unit price, total
            # Validate: qty * unit_price ≈ total
            qty, price, total = numbers[0], numbers[1], numbers[2]

            # Check if multiplication makes sense
            if abs(qty * price - total) / total < 0.1:  # Within 10%
                return qty, price, total
            else:
                # Maybe first is item number, not qty
                return numbers[1], numbers[2], numbers[2]

        if len(numbers) >= 4:
            # Multiple numbers - take last 3
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
        if qty and unit_price and abs(qty * unit_price - total) / total < 0.05:
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
        Validate line items against totals
        Remove invalid items
        """
        validated = []

        # Calculate sum of line items
        items_total = sum(item.total_price for item in line_items)

        # Check if sum matches invoice total
        invoice_total = totals.get('total') or totals.get('subtotal')

        if invoice_total:
            # If items total is close to invoice total, good
            if abs(items_total - invoice_total) / invoice_total < 0.1:
                # All items are valid
                for item in line_items:
                    validated.append({
                        'description': item.description,
                        'quantity': item.quantity,
                        'unit_price': item.unit_price,
                        'total': item.total_price,
                        'confidence': min(item.confidence + 0.1, 1.0)  # Boost confidence
                    })
            else:
                # Some items might be invalid - use confidence scores
                for item in line_items:
                    if item.confidence > 0.6:  # Only include confident items
                        validated.append({
                            'description': item.description,
                            'quantity': item.quantity,
                            'unit_price': item.unit_price,
                            'total': item.total_price,
                            'confidence': item.confidence
                        })
        else:
            # No total to validate against - include all items
            for item in line_items:
                validated.append({
                    'description': item.description,
                    'quantity': item.quantity,
                    'unit_price': item.unit_price,
                    'total': item.total_price,
                    'confidence': item.confidence
                })

        return validated

    def _calculate_confidence(self, header_info: Dict, line_items: List[Dict], totals: Dict) -> float:
        """Calculate overall extraction confidence"""
        confidence_factors = []

        # Header info
        if header_info.get('vendor'):
            confidence_factors.append(0.9)
        if header_info.get('invoice_number'):
            confidence_factors.append(0.9)
        if header_info.get('date'):
            confidence_factors.append(0.9)

        # Line items
        if line_items:
            avg_item_confidence = np.mean([item['confidence'] for item in line_items])
            confidence_factors.append(avg_item_confidence)

        # Totals
        if totals.get('total'):
            confidence_factors.append(0.95)

        return np.mean(confidence_factors) if confidence_factors else 0.3


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

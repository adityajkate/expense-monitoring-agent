"""
Invoice OCR and Data Extraction System
Handles PDF and image uploads, extracts structured data using OCR and NLP
"""

import os
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import io

# OCR and Image Processing
try:
    import pytesseract
    from pdf2image import convert_from_bytes
    from PIL import Image, ImageEnhance, ImageFilter
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    print("Warning: OCR dependencies not fully installed")

# NLP
import spacy
from spacy.matcher import Matcher

# Data processing
import pandas as pd
import numpy as np

# Intelligent parser
from intelligent_parser import IntelligentInvoiceParser


class InvoiceOCR:
    """OCR and data extraction for invoices and receipts"""

    def __init__(self, tesseract_path: Optional[str] = None):
        """
        Initialize OCR system

        Args:
            tesseract_path: Path to tesseract executable (optional)
        """
        self.tesseract_available = TESSERACT_AVAILABLE

        # Set Tesseract path
        if not tesseract_path:
            tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        if tesseract_path and TESSERACT_AVAILABLE:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        # Set Poppler path for pdf2image
        poppler_path = r"C:\Program Files\poppler-25.12.0\Library\bin"
        if os.path.exists(poppler_path):
            os.environ["PATH"] = poppler_path + os.pathsep + os.environ.get("PATH", "")

        # Load spaCy model for NER
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("Warning: spaCy model not found. Run: python -m spacy download en_core_web_sm")
            self.nlp = None

        # Initialize matcher for patterns
        if self.nlp:
            self.matcher = Matcher(self.nlp.vocab)
            self._setup_patterns()

        # Initialize intelligent parser
        self.intelligent_parser = IntelligentInvoiceParser()

    def _setup_patterns(self):
        """Set up spaCy patterns for common invoice fields"""
        # Invoice number patterns
        invoice_pattern = [
            {"LOWER": {"IN": ["invoice", "inv", "bill"]}},
            {"LOWER": {"IN": ["no", "number", "#"]}, "OP": "?"},
            {"IS_PUNCT": True, "OP": "?"},
            {"IS_DIGIT": True}
        ]
        self.matcher.add("INVOICE_NUMBER", [invoice_pattern])

        # Date patterns
        date_pattern = [
            {"LOWER": {"IN": ["date", "dated", "on"]}},
            {"IS_PUNCT": True, "OP": "?"},
            {"SHAPE": {"IN": ["dd/dd/dddd", "dd-dd-dddd"]}}
        ]
        self.matcher.add("DATE", [date_pattern])

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess image for better OCR accuracy with adaptive enhancements

        Args:
            image: PIL Image object

        Returns:
            Preprocessed image
        """
        import cv2
        import numpy as np

        # Convert PIL to numpy array for OpenCV processing
        img_array = np.array(image)

        # Convert to grayscale if not already
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        # 1. ROTATION DETECTION AND CORRECTION
        # Detect rotation angle using line detection
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)

        if lines is not None:
            angles = []
            for line in lines[:20]:  # Check first 20 lines
                rho, theta = line[0]  # HoughLines returns array of [[rho, theta]]
                angle = np.degrees(theta) - 90
                if -45 < angle < 45:  # Only consider reasonable rotations
                    angles.append(angle)

            if angles:
                # Use median angle to avoid outliers
                rotation_angle = np.median(angles)

                # Rotate if angle is significant (> 2 degrees)
                if abs(rotation_angle) > 2:
                    (h, w) = gray.shape
                    center = (w // 2, h // 2)
                    M = cv2.getRotationMatrix2D(center, rotation_angle, 1.0)
                    gray = cv2.warpAffine(gray, M, (w, h),
                                         flags=cv2.INTER_CUBIC,
                                         borderMode=cv2.BORDER_REPLICATE)

        # 2. ADAPTIVE CONTRAST ENHANCEMENT
        # Calculate current contrast level
        contrast = gray.std()

        # Only enhance if contrast is low (< 50)
        if contrast < 50:
            # Use CLAHE (Contrast Limited Adaptive Histogram Equalization)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)

        # 3. ADAPTIVE BINARIZATION (Otsu's method)
        # This automatically finds optimal threshold
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 4. NOISE REDUCTION
        # Use bilateral filter to preserve edges while removing noise
        denoised = cv2.bilateralFilter(binary, 5, 75, 75)

        # 5. RESIZE if needed (OCR works better on larger images)
        height, width = denoised.shape
        if width < 1000:
            scale = 1000 / width
            new_width = int(width * scale)
            new_height = int(height * scale)
            denoised = cv2.resize(denoised, (new_width, new_height),
                                 interpolation=cv2.INTER_CUBIC)

        # Convert back to PIL Image
        return Image.fromarray(denoised)

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """
        Extract text from PDF using OCR with multi-pass strategy

        Args:
            pdf_bytes: PDF file as bytes

        Returns:
            Extracted text
        """
        if not self.tesseract_available:
            raise RuntimeError("Tesseract OCR not available. Please install it first.")

        # Convert PDF to images
        images = convert_from_bytes(pdf_bytes, dpi=300)

        # OCR each page
        text_parts = []
        for i, image in enumerate(images):
            # Preprocess
            processed = self.preprocess_image(image)

            # Multi-pass OCR: Try different PSM modes and pick best result
            page_text = self._multi_pass_ocr(processed)
            text_parts.append(f"--- Page {i+1} ---\n{page_text}")

        return "\n\n".join(text_parts)

    def _multi_pass_ocr(self, image: Image.Image) -> str:
        """
        Try multiple PSM modes and return best result

        Args:
            image: Preprocessed PIL Image

        Returns:
            Best OCR result
        """
        psm_modes = [
            (6, '--psm 6'),  # Uniform block of text (current default)
            (3, '--psm 3'),  # Fully automatic page segmentation
            (11, '--psm 11') # Sparse text (good for invoices with whitespace)
        ]

        best_text = ""
        best_confidence = 0.0

        for psm_num, config in psm_modes:
            try:
                # Get text and confidence data
                data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)

                # Calculate average confidence (excluding -1 values)
                confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0

                # Get text
                text = pytesseract.image_to_string(image, config=config)

                # Pick result with highest confidence
                if avg_confidence > best_confidence and len(text.strip()) > 50:
                    best_confidence = avg_confidence
                    best_text = text

            except Exception as e:
                # If a PSM mode fails, continue to next
                continue

        # Fallback to PSM 6 if all failed
        if not best_text:
            best_text = pytesseract.image_to_string(image, config='--psm 6')

        return best_text

    def extract_text_from_image(self, image_bytes: bytes) -> str:
        """
        Extract text from image using OCR with multi-pass strategy

        Args:
            image_bytes: Image file as bytes

        Returns:
            Extracted text
        """
        if not self.tesseract_available:
            raise RuntimeError("Tesseract OCR not available. Please install it first.")

        # Load image
        image = Image.open(io.BytesIO(image_bytes))

        # Preprocess
        processed = self.preprocess_image(image)

        # Multi-pass OCR
        text = self._multi_pass_ocr(processed)

        return text

    def extract_vendor(self, text: str) -> Tuple[str, float]:
        """
        Extract vendor name from invoice text using multiple strategies

        Args:
            text: OCR extracted text

        Returns:
            Tuple of (vendor_name, confidence)
        """
        if not self.nlp:
            return "Unknown", 0.0

        vendors = []

        # Strategy 1: spaCy NER for ORG entities
        doc = self.nlp(text[:1000])  # First 1000 chars usually have vendor
        orgs = [ent.text for ent in doc.ents if ent.label_ == "ORG"]
        for org in orgs:
            # Filter out common noise patterns
            if not re.match(r'^(Page|\d+|---|\||Invoice|Bill|Date)', org, re.IGNORECASE):
                if len(org) > 3:  # Must be at least 4 characters
                    vendors.append((org, 0.9))
                    break  # Take first valid org

        # Strategy 2: Look for "From:", "Vendor:", "Bill From:" keywords
        keyword_patterns = [
            r'(?:From|Vendor|Bill From|Billed By)\s*:?\s*([A-Za-z0-9\s&.,\'-]+?)(?:\n|$)',
            r'(?:Company|Business)\s*:?\s*([A-Za-z0-9\s&.,\'-]+?)(?:\n|$)',
        ]
        for pattern in keyword_patterns:
            match = re.search(pattern, text[:500], re.IGNORECASE)
            if match:
                vendor_name = match.group(1).strip()
                if len(vendor_name) > 3:  # Avoid single letters
                    vendors.append((vendor_name, 0.85))
                    break

        # Strategy 3: First non-empty line (common position)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for line in lines[:10]:  # Check first 10 lines
            # Skip page markers, dates, invoice numbers
            if re.match(r'^(---|Page|\d+|Invoice|Bill|Date|From|To)', line, re.IGNORECASE):
                continue
            # Skip lines that are just numbers or dates
            if re.match(r'^[\d\s/\-:]+$', line):
                continue
            # Skip very short lines
            if len(line) < 4:
                continue
            # This looks like a company name
            vendors.append((line[:50], 0.6))
            break

        # Pick best vendor by confidence
        if vendors:
            vendors.sort(key=lambda x: x[1], reverse=True)
            return vendors[0][0], vendors[0][1]

        return "Unknown", 0.3

    def extract_invoice_number(self, text: str) -> Optional[str]:
        """
        Extract invoice number from text with more flexible patterns

        Args:
            text: OCR extracted text

        Returns:
            Invoice number or None
        """
        # Extended patterns for various invoice number formats
        patterns = [
            r'Invoice\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'INV\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'Bill\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'Reference\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'PO\s*#?\s*:?\s*([A-Z0-9-]+)',  # Purchase Order
            r'Order\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'Doc(?:ument)?\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'Ref\s*#?\s*:?\s*([A-Z0-9-]+)',
            r'#\s*([A-Z0-9-]{3,})',  # Just # followed by alphanumeric
            # Alphanumeric patterns like INV-2024-001, PO123456
            r'\b(INV-?\d{4,})\b',
            r'\b(PO\d{6,})\b',
            r'\b([A-Z]{2,}\d{4,})\b',  # Like ABC1234
        ]

        for pattern in patterns:
            match = re.search(pattern, text[:1500], re.IGNORECASE)  # Check first 1500 chars
            if match:
                invoice_num = match.group(1).strip()
                # Validate: should have at least one digit and be reasonable length
                if re.search(r'\d', invoice_num) and 3 <= len(invoice_num) <= 30:
                    # Filter out common false positives
                    if not re.match(r'^(Page|\d{1,2})$', invoice_num, re.IGNORECASE):
                        return invoice_num

        return None

    def extract_date(self, text: str) -> Optional[str]:
        """
        Extract invoice date from text with better parsing

        Args:
            text: OCR extracted text

        Returns:
            Date string in YYYY-MM-DD format or None
        """
        from dateutil import parser as date_parser

        # Date patterns - more comprehensive
        patterns = [
            r'(?:Invoice\s+)?Date\s*:?\s*([A-Za-z0-9\s,/-]+)',
            r'Dated\s*:?\s*([A-Za-z0-9\s,/-]+)',
            r'(?:Issue|Issued)\s+(?:Date|On)\s*:?\s*([A-Za-z0-9\s,/-]+)',
            r'Date\s+of\s+Invoice\s*:?\s*([A-Za-z0-9\s,/-]+)',
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',
            r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text[:1500], re.IGNORECASE)  # Check first 1500 chars
            if match:
                date_str = match.group(1).strip()

                # Clean up the date string
                date_str = re.sub(r'\s+', ' ', date_str)  # Normalize whitespace

                # Try to parse with dateutil (handles many formats)
                try:
                    dt = date_parser.parse(date_str, fuzzy=True)

                    # Validate date is reasonable (not in future, not too old)
                    from datetime import datetime, timedelta
                    now = datetime.now()
                    if dt and dt <= now and dt >= now - timedelta(days=3650):  # Within last 10 years
                        return dt.strftime('%Y-%m-%d')
                except:
                    # If dateutil fails, try manual parsing
                    try:
                        for fmt in ['%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d', '%m-%d-%Y', '%d-%m-%Y', '%Y/%m/%d', '%d %B %Y', '%B %d, %Y', '%d %b %Y', '%b %d, %Y']:
                            try:
                                dt = datetime.strptime(date_str, fmt)
                                return dt.strftime('%Y-%m-%d')
                            except ValueError:
                                continue
                    except:
                        pass

        return None

    def extract_amounts(self, text: str) -> Dict[str, float]:
        """
        Extract monetary amounts from text with validation

        Args:
            text: OCR extracted text

        Returns:
            Dictionary with amount types and values
        """
        amounts = {}

        # Look for specific amount keywords first (more accurate)
        total_patterns = [
            r'(?:Total|Amount Due|Balance Due|Grand Total|Total Amount|Amount Payable|Net Total)\s*:?\s*\$?\s*([\d,]+\.?\d{0,2})',
            r'(?:Total|Amount)\s*:?\s*\$?\s*([\d,]+\.?\d{0,2})',
            r'\$\s*([\d,]+\.?\d{2})\s*(?:Total|Due)',
        ]

        for pattern in total_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    value = float(match.group(1).replace(',', ''))
                    if value > 0:  # Must be positive
                        amounts['total'] = value
                        break
                except ValueError:
                    continue
            if 'total' in amounts:
                break

        # Look for subtotal
        subtotal_patterns = [
            r'Subtotal\s*:?\s*\$?\s*([\d,]+\.?\d{0,2})',
            r'Sub-Total\s*:?\s*\$?\s*([\d,]+\.?\d{0,2})',
            r'Sub Total\s*:?\s*\$?\s*([\d,]+\.?\d{0,2})',
        ]
        for pattern in subtotal_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    if value > 0:
                        amounts['subtotal'] = value
                        break
                except ValueError:
                    continue

        # Look for tax
        tax_patterns = [
            r'(?:Tax|VAT|GST|Sales Tax)\s*:?\s*\$?\s*([\d,]+\.?\d{0,2})',
            r'(?:Tax|VAT|GST)\s*\([\d.]+%\)\s*:?\s*\$?\s*([\d,]+\.?\d{0,2})',
        ]
        for pattern in tax_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    if value > 0:
                        amounts['tax'] = value
                        break
                except ValueError:
                    continue

        # If no total found, find all amounts and pick largest reasonable one
        if 'total' not in amounts:
            # More flexible pattern - handles amounts with or without decimals
            currency_pattern = r'\$\s*([\d,]+(?:\.\d{1,2})?)|(?:^|\s)([\d,]+\.\d{2})(?:\s|$)'
            matches = re.findall(currency_pattern, text)

            if matches:
                values = []
                for match in matches:
                    # match is a tuple, get the non-empty group
                    amount_str = match[0] if match[0] else match[1]
                    if amount_str:
                        try:
                            value = float(amount_str.replace(',', ''))
                            # Filter out unreasonable values (too small or too large)
                            if 1 <= value <= 1000000:
                                values.append(value)
                        except ValueError:
                            continue

                if values:
                    # Pick the largest value as total
                    amounts['total'] = max(values)

        # Validate: subtotal + tax should equal total (within 2%)
        if 'total' in amounts and 'subtotal' in amounts and 'tax' in amounts:
            calculated_total = amounts['subtotal'] + amounts['tax']
            diff_pct = abs(calculated_total - amounts['total']) / amounts['total']

            if diff_pct > 0.02:  # More than 2% difference
                # Flag as potential error but keep the values
                amounts['validation_warning'] = f"Calculation mismatch: {diff_pct:.1%} difference"

        return amounts

    def extract_line_items(self, text: str) -> List[Dict[str, any]]:
        """
        Extract line items from invoice

        Args:
            text: OCR extracted text

        Returns:
            List of line items with description, quantity, price
        """
        line_items = []

        # Look for table-like structures
        lines = text.split('\n')

        # Common line item patterns
        item_pattern = r'(.+?)\s+(\d+)\s+\$?\s*([\d,]+\.?\d*)'

        for line in lines:
            match = re.search(item_pattern, line)
            if match:
                description = match.group(1).strip()
                quantity = int(match.group(2))
                price = float(match.group(3).replace(',', ''))

                line_items.append({
                    'description': description,
                    'quantity': quantity,
                    'unit_price': price,
                    'total': quantity * price
                })

        return line_items

    def _is_placeholder_vendor(self, vendor: Optional[str]) -> bool:
        """Return True when a vendor value is empty or obviously wrong."""
        if not vendor:
            return True

        vendor_lower = vendor.strip().lower()
        if vendor_lower in {"unknown", "n/a"}:
            return True

        return bool(re.match(r'^(---\s*page|page\s+\d+|bill\s+to|date\b|invoice\b)', vendor_lower))

    def _is_valid_invoice_number(self, invoice_number: Optional[str]) -> bool:
        """Return True when the invoice number looks usable."""
        return bool(
            invoice_number and
            len(invoice_number.strip()) >= 4 and
            re.search(r'\d', invoice_number)
        )

    def _normalize_date_value(self, raw_date: Optional[str]) -> Optional[str]:
        """Normalize dates to YYYY-MM-DD when possible."""
        if not raw_date:
            return None

        from dateutil import parser as date_parser

        try:
            return date_parser.parse(raw_date, fuzzy=True).strftime('%Y-%m-%d')
        except Exception:
            return raw_date

    def _looks_like_normalized_date(self, raw_date: Optional[str]) -> bool:
        """Return True when the date is already in a stable format."""
        return bool(raw_date and re.match(r'^\d{4}-\d{2}-\d{2}$', raw_date))

    def _normalize_vendor_name(self, vendor: Optional[str]) -> Optional[str]:
        """Clean OCR artifacts from vendor names."""
        if not vendor:
            return vendor

        vendor = re.sub(r'\s+', ' ', vendor).strip()
        vendor = re.sub(r'([a-z])([A-Z])', r'\1 \2', vendor)
        vendor = re.sub(r'([A-Z]{2,})([A-Z][a-z])', r'\1 \2', vendor)
        return vendor

    def _align_invoice_number_year(self, invoice_number: Optional[str], normalized_date: Optional[str]) -> Optional[str]:
        """Align embedded invoice-number year with the parsed document date when off by one OCR digit."""
        if not invoice_number or not normalized_date or not self._looks_like_normalized_date(normalized_date):
            return invoice_number

        match = re.search(r'(20\d{2})', invoice_number)
        if not match:
            return invoice_number

        invoice_year = match.group(1)
        date_year = normalized_date[:4]

        if invoice_year == date_year:
            return invoice_number

        distance = sum(1 for a, b in zip(invoice_year, date_year) if a != b)
        if distance == 1 and invoice_year[:3] == date_year[:3]:
            return invoice_number.replace(invoice_year, date_year, 1)

        return invoice_number

    def _line_items_total(self, line_items: List[Dict]) -> float:
        """Return the sum of line-item totals."""
        return sum(float(item.get('total', 0) or 0) for item in line_items)

    def extract_invoice_data(self, file_bytes: bytes, file_type: str) -> Dict:
        """
        Extract all structured data from invoice using intelligent parsing

        Args:
            file_bytes: File content as bytes
            file_type: 'pdf' or 'image'

        Returns:
            Dictionary with extracted data
        """
        # Extract text
        if file_type == 'pdf':
            text = self.extract_text_from_pdf(file_bytes)
        else:
            text = self.extract_text_from_image(file_bytes)

        # Use intelligent parser to understand invoice structure
        parsed_data = self.intelligent_parser.parse_invoice_with_layout(text)

        # Always run fallback extraction as a second opinion.
        # OCR on PDFs is noisy enough that regex-based recovery often fixes missing fields.
        vendor, vendor_confidence = self.extract_vendor(text)
        invoice_number = self.extract_invoice_number(text)
        date = self._normalize_date_value(self.extract_date(text))
        amounts = self.extract_amounts(text)
        line_items = self.extract_line_items(text)

        if parsed_data['confidence'] < 0.5:
            print("Low confidence from intelligent parser, using fallback extraction...")

        parsed_data['date'] = self._normalize_date_value(parsed_data.get('date'))

        if self._is_placeholder_vendor(parsed_data.get('vendor')) and vendor:
            parsed_data['vendor'] = vendor

        if not self._is_valid_invoice_number(parsed_data.get('invoice_number')) and invoice_number:
            parsed_data['invoice_number'] = invoice_number

        if not self._looks_like_normalized_date(parsed_data.get('date')) and date:
            parsed_data['date'] = date

        parsed_data['vendor'] = self._normalize_vendor_name(parsed_data.get('vendor'))
        parsed_data['invoice_number'] = self._align_invoice_number_year(
            parsed_data.get('invoice_number'),
            parsed_data.get('date')
        )

        if (not parsed_data.get('total')) and amounts.get('total'):
            parsed_data['total'] = amounts['total']
        if (not parsed_data.get('subtotal')) and amounts.get('subtotal'):
            parsed_data['subtotal'] = amounts.get('subtotal')
        if (not parsed_data.get('tax')) and amounts.get('tax'):
            parsed_data['tax'] = amounts.get('tax')

        parsed_items = parsed_data.get('line_items', [])
        parsed_item_total = self._line_items_total(parsed_items)
        fallback_item_total = self._line_items_total(line_items)
        subtotal_target = parsed_data.get('subtotal') or amounts.get('subtotal') or parsed_data.get('total')

        if not parsed_items and line_items:
            parsed_data['line_items'] = line_items
        elif subtotal_target and line_items:
            parsed_diff = abs(parsed_item_total - subtotal_target)
            fallback_diff = abs(fallback_item_total - subtotal_target)
            if fallback_diff < parsed_diff:
                parsed_data['line_items'] = line_items

        reconciled_items_total = round(self._line_items_total(parsed_data.get('line_items', [])), 2)
        subtotal_value = parsed_data.get('subtotal')
        tax_value = parsed_data.get('tax')
        total_value = parsed_data.get('total')

        if subtotal_value and tax_value:
            calculated_total = round(subtotal_value + tax_value, 2)
            if not total_value or abs(calculated_total - total_value) / calculated_total > 0.02:
                parsed_data['total'] = calculated_total

        if not parsed_data.get('subtotal') and reconciled_items_total > 0:
            parsed_data['subtotal'] = reconciled_items_total
        elif parsed_data.get('subtotal') and reconciled_items_total > 0:
            if abs(parsed_data['subtotal'] - reconciled_items_total) / parsed_data['subtotal'] < 0.02:
                parsed_data['subtotal'] = reconciled_items_total

        # Format amounts for consistency
        amounts_dict = {
            'total': parsed_data.get('total', 0),
            'subtotal': parsed_data.get('subtotal'),
            'tax': parsed_data.get('tax')
        }

        # Format line items
        line_items_formatted = []
        for item in parsed_data.get('line_items', []):
            line_items_formatted.append({
                'description': item['description'],
                'quantity': item.get('quantity'),
                'unit_price': item.get('unit_price'),
                'total': item['total'],
                'confidence': item.get('confidence', 0.7)
            })

        parser_used = 'intelligent'
        if parsed_data['confidence'] < 0.5:
            parser_used = 'fallback'
        elif vendor_confidence >= 0.85 or invoice_number or date:
            parser_used = 'hybrid'

        return {
            'vendor': parsed_data.get('vendor', 'Unknown'),
            'invoice_number': parsed_data.get('invoice_number'),
            'date': parsed_data.get('date'),
            'amounts': amounts_dict,
            'line_items': line_items_formatted,
            'raw_text': text,
            'confidence': parsed_data.get('confidence', 0.5),
            'extraction_timestamp': datetime.now().isoformat(),
            'parser_used': parser_used
        }


if __name__ == "__main__":
    """Test the OCR system"""
    print("=" * 80)
    print("INVOICE OCR SYSTEM TEST")
    print("=" * 80)

    ocr = InvoiceOCR()

    if not ocr.tesseract_available:
        print("\nError: Tesseract OCR not installed")
        print("Please install Tesseract first. See TESSERACT_INSTALL.md")
        exit(1)

    print("\nOCR system initialized successfully!")
    print("Ready to process invoices and receipts.")
    print("\nSupported formats:")
    print("  - PDF (multi-page)")
    print("  - Images (JPG, PNG, TIFF)")
    print("\nFeatures:")
    print("  - Vendor extraction")
    print("  - Invoice number detection")
    print("  - Date parsing")
    print("  - Amount extraction (total, subtotal, tax)")
    print("  - Line item parsing")
    print("  - Confidence scoring")

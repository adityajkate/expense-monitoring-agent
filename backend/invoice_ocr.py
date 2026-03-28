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

        if tesseract_path and TESSERACT_AVAILABLE:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

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
        Preprocess image for better OCR accuracy

        Args:
            image: PIL Image object

        Returns:
            Preprocessed image
        """
        # Convert to grayscale
        image = image.convert('L')

        # Increase contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)

        # Sharpen
        image = image.filter(ImageFilter.SHARPEN)

        # Denoise
        image = image.filter(ImageFilter.MedianFilter(size=3))

        # Resize if too small (OCR works better on larger images)
        width, height = image.size
        if width < 1000:
            scale = 1000 / width
            new_size = (int(width * scale), int(height * scale))
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        return image

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """
        Extract text from PDF using OCR

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

            # OCR
            page_text = pytesseract.image_to_string(processed, config='--psm 6')
            text_parts.append(f"--- Page {i+1} ---\n{page_text}")

        return "\n\n".join(text_parts)

    def extract_text_from_image(self, image_bytes: bytes) -> str:
        """
        Extract text from image using OCR

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

        # OCR
        text = pytesseract.image_to_string(processed, config='--psm 6')

        return text

    def extract_vendor(self, text: str) -> Tuple[str, float]:
        """
        Extract vendor name from invoice text

        Args:
            text: OCR extracted text

        Returns:
            Tuple of (vendor_name, confidence)
        """
        if not self.nlp:
            return "Unknown", 0.0

        # Process text with spaCy
        doc = self.nlp(text[:1000])  # First 1000 chars usually have vendor

        # Extract organizations
        orgs = [ent.text for ent in doc.ents if ent.label_ == "ORG"]

        if orgs:
            # First organization is usually the vendor
            return orgs[0], 0.9
        else:
            # Fallback: first line often has vendor name
            first_line = text.split('\n')[0].strip()
            return first_line[:50], 0.5

    def extract_invoice_number(self, text: str) -> Optional[str]:
        """
        Extract invoice number from text

        Args:
            text: OCR extracted text

        Returns:
            Invoice number or None
        """
        # Common patterns
        patterns = [
            r'Invoice\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'INV\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'Bill\s*(?:No|Number|#)?\s*:?\s*([A-Z0-9-]+)',
            r'Reference\s*:?\s*([A-Z0-9-]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def extract_date(self, text: str) -> Optional[str]:
        """
        Extract invoice date from text

        Args:
            text: OCR extracted text

        Returns:
            Date string or None
        """
        # Date patterns
        patterns = [
            r'Date\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'Dated\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                # Try to parse and normalize
                try:
                    # Try multiple formats
                    for fmt in ['%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%d', '%m-%d-%Y', '%d-%m-%Y']:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            return dt.strftime('%Y-%m-%d')
                        except ValueError:
                            continue
                except:
                    pass
                return date_str

        return None

    def extract_amounts(self, text: str) -> Dict[str, float]:
        """
        Extract monetary amounts from text

        Args:
            text: OCR extracted text

        Returns:
            Dictionary with amount types and values
        """
        amounts = {}

        # Find all currency amounts
        currency_pattern = r'\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
        matches = re.findall(currency_pattern, text)

        if matches:
            # Convert to floats
            values = []
            for match in matches:
                try:
                    value = float(match.replace(',', ''))
                    if value > 0:
                        values.append(value)
                except ValueError:
                    continue

            if values:
                # Total is usually the largest amount
                amounts['total'] = max(values)

                # Try to find subtotal, tax
                subtotal_match = re.search(r'Subtotal\s*:?\s*\$?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
                if subtotal_match:
                    amounts['subtotal'] = float(subtotal_match.group(1).replace(',', ''))

                tax_match = re.search(r'Tax\s*:?\s*\$?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
                if tax_match:
                    amounts['tax'] = float(tax_match.group(1).replace(',', ''))

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

        # Fallback to basic extraction if intelligent parser has low confidence
        if parsed_data['confidence'] < 0.5:
            print("Low confidence from intelligent parser, using fallback extraction...")

            # Fallback extraction
            vendor, vendor_confidence = self.extract_vendor(text)
            invoice_number = self.extract_invoice_number(text)
            date = self.extract_date(text)
            amounts = self.extract_amounts(text)
            line_items = self.extract_line_items(text)

            # Use whichever has better data
            if not parsed_data['vendor'] and vendor:
                parsed_data['vendor'] = vendor
            if not parsed_data['invoice_number'] and invoice_number:
                parsed_data['invoice_number'] = invoice_number
            if not parsed_data['date'] and date:
                parsed_data['date'] = date
            if not parsed_data['line_items'] and line_items:
                parsed_data['line_items'] = line_items
            if not parsed_data['total'] and amounts.get('total'):
                parsed_data['total'] = amounts['total']
                parsed_data['subtotal'] = amounts.get('subtotal')
                parsed_data['tax'] = amounts.get('tax')

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

        return {
            'vendor': parsed_data.get('vendor', 'Unknown'),
            'invoice_number': parsed_data.get('invoice_number'),
            'date': parsed_data.get('date'),
            'amounts': amounts_dict,
            'line_items': line_items_formatted,
            'raw_text': text,
            'confidence': parsed_data.get('confidence', 0.5),
            'extraction_timestamp': datetime.now().isoformat(),
            'parser_used': 'intelligent' if parsed_data['confidence'] >= 0.5 else 'fallback'
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

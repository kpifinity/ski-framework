"""
Utility functions for KG Extractor
"""

import os
from typing import List
from .models import ComplianceRule


def extract_text_from_document(file_path: str) -> str:
    """
    Extract text from various document formats

    Args:
        file_path: Path to document

    Returns:
        Extracted text
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document not found: {file_path}")

    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    if ext == ".txt":
        return _extract_from_txt(file_path)
    elif ext == ".pdf":
        return _extract_from_pdf(file_path)
    elif ext == ".html":
        return _extract_from_html(file_path)
    elif ext == ".docx":
        return _extract_from_docx(file_path)
    elif ext == ".md":
        return _extract_from_markdown(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext}")


def _extract_from_txt(file_path: str) -> str:
    """Extract text from .txt file"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_from_pdf(file_path: str) -> str:
    """Extract text from PDF file"""
    try:
        import PyPDF2
    except ImportError:
        raise ImportError("PyPDF2 required for PDF extraction. Install with: pip install PyPDF2")

    text = []
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text.append(page.extract_text())

    return "\n".join(text)


def _extract_from_html(file_path: str) -> str:
    """Extract text from HTML file"""
    try:
        from html.parser import HTMLParser
    except ImportError:
        raise ImportError("HTML parser not available")

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = []

        def handle_data(self, data):
            self.text.append(data)

    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()

    parser = TextExtractor()
    parser.feed(html)
    return "\n".join(parser.text)


def _extract_from_docx(file_path: str) -> str:
    """Extract text from DOCX file"""
    try:
        from docx import Document
    except ImportError:
        raise ImportError("python-docx required for DOCX extraction. Install with: pip install python-docx")

    doc = Document(file_path)
    text = []

    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            text.append(paragraph.text)

    return "\n".join(text)


def _extract_from_markdown(file_path: str) -> str:
    """Extract text from Markdown file"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def chunk_text(text: str, max_chunk_size: int = 4000, overlap: int = 200) -> List[str]:
    """
    Split text into overlapping chunks for processing

    Args:
        text: Text to chunk
        max_chunk_size: Maximum size of each chunk
        overlap: Number of characters to overlap between chunks

    Returns:
        List of text chunks
    """
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + max_chunk_size, len(text))

        # Try to break at sentence boundary
        if end < len(text):
            # Look back for a period
            lookback_end = end
            while lookback_end > start + max_chunk_size // 2:
                if text[lookback_end] in ".!?\n":
                    end = lookback_end + 1
                    break
                lookback_end -= 1

        chunks.append(text[start:end])

        # Move start position with overlap
        start = end - overlap
        if start < 0:
            start = 0

    return chunks


def validate_rule(rule: ComplianceRule) -> bool:
    """
    Validate that a rule has required fields

    Args:
        rule: ComplianceRule to validate

    Returns:
        True if rule is valid, False otherwise
    """
    required_fields = ["subject", "relation", "object"]

    for field in required_fields:
        value = getattr(rule, field, None)
        if not value or not isinstance(value, str) or not value.strip():
            return False

    return True

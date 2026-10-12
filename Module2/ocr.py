
from pdf2image import convert_from_path
import pytesseract
import re
from PIL import ImageEnhance, ImageOps


def ocr_extract_pdf(pdf_path):
    # Improved rendering resolution for small PDF text
    images = convert_from_path(pdf_path, dpi=300)

    full_text = ""

    for i, img in enumerate(images):

        # Improve image readability before OCR
        gray_img = ImageOps.grayscale(img)

        # Mild contrast enhancement
        enhanced_img = ImageEnhance.Contrast(
            gray_img
        ).enhance(1.5)

        # Automatic page segmentation
        text = pytesseract.image_to_string(
            enhanced_img,
            config="--oem 3 --psm 6"
        )

        full_text += text + "\n"

    return clean_ocr_text(full_text)


def clean_ocr_text(text):

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Fix common OCR misrecognitions of '11' before am/pm
    text = re.sub(
        r'(?i)\b(JJ|J/|J\]|Il|1l|II|ll)\s*([ap]\.?m\.?)',
        r'11 \2',
        text
    )

    # Fix single l/I misrecognized after between/from
    text = re.sub(
        r'(?i)\b(between|from)\s+[lI]\s*([ap]\.?m\.?)',
        r'\1 11 \2',
        text
    )

    # Fix missing spaces before digits in time ranges
    text = re.sub(
        r'(?i)\bto(\d+)\s*([ap]\.?m\.?)',
        r'to \1 \2',
        text
    )

    # Fix spaces accidentally inserted inside numeric dates
    # Example: 01.1 0.2026 -> 01.10.2026
    text = re.sub(
        r'\b(\d{1,2}[./-]\d)\s+(\d[./-]\d{4})\b',
        r'\1\2',
        text
    )

    # Trim OCR noise from university logo at the top
    header_patterns = [
        r'MAULANA\s+ABUL\s+KALAM\s+AZAD\s+UNIVERSITY',
        r'WEST\s+BENGAL\s+UNIVERSITY\s+OF\s+TECHNOLOGY',
        r'MAKAUT',
        r'OFFICE\s+OF\s+THE\s+(?:REGISTRAR|CONTROLLER|VICE[\s-]CHANCELLOR)',
    ]

    combined_header = re.compile(
        '|'.join(header_patterns),
        re.IGNORECASE
    )

    raw_lines = text.split("\n")

    start_idx = 0

    for idx, line in enumerate(raw_lines):
        if combined_header.search(line):
            start_idx = idx
            break

    lines = raw_lines[start_idx:]

    cleaned = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        # Remove known isolated logo artifacts
        if stripped.lower() in ["utech", "u-tech"]:
            continue

        # Preserve short numbers, dates, and numbered items
        # rather than discarding all short lines.

        cleaned.append(
            re.sub(r'[ \t]+', ' ', stripped)
        )

    return "\n".join(cleaned)

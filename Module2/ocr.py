from pdf2image import convert_from_path
import pytesseract
import re

def ocr_extract_pdf(pdf_path):
    images = convert_from_path(pdf_path)
    full_text = ""
    for i, img in enumerate(images):
        text = pytesseract.image_to_string(img)
        full_text += text + "\n"
    return clean_ocr_text(full_text)


def clean_ocr_text(text):
    # Fix common OCR misrecognitions of '11' before am/pm (e.g. JJ a.m., J/ a.m., J] a.m., Il a.m., 1l a.m., II a.m., ll a.m.)
    text = re.sub(r'(?i)\b(JJ|J/|J\]|Il|1l|II|ll)\s*([ap]\.?m\.?)', r'11 \2', text)
    # Fix single 'l' or 'I' misrecognized as 1 or 11 after 'between' or 'from'
    text = re.sub(r'(?i)\b(between|from)\s+[lI]\s*([ap]\.?m\.?)', r'\1 11 \2', text)
    # Fix missing spaces before digits in time ranges, e.g. 'to4 p.m.' -> 'to 4 p.m.'
    text = re.sub(r'(?i)\bto(\d+)\s*([ap]\.?m\.?)', r'to \1 \2', text)

    # Trim OCR noise from the university logo emblem at the top of the notice
    # (e.g. 'oyna ams waa nan', 'Min', '(eel', etc. above the official header)
    header_patterns = [
        r'MAULANA\s+ABUL\s+KALAM\s+AZAD\s+UNIVERSITY',
        r'WEST\s+BENGAL\s+UNIVERSITY\s+OF\s+TECHNOLOGY',
        r'MAKAUT',
        r'OFFICE\s+OF\s+THE\s+(?:REGISTRAR|CONTROLLER|VICE[\s\-]CHANCELLOR)',
    ]
    combined_header = re.compile('|'.join(header_patterns), re.IGNORECASE)

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
        # Skip isolated logo artifacts (like 'Utech')
        if stripped.lower() in ["utech", "u-tech"]:
            continue
        # Skip very short, non-alphabetic noise lines (common OCR artifacts from logos/signatures)
        if len(stripped) < 4 and not stripped.isalpha():
            continue
        cleaned.append(line)
    return "\n".join(cleaned)
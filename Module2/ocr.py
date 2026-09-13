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
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip very short, non-alphabetic noise lines (common OCR artifacts from logos/signatures)
        if len(stripped) < 4 and not stripped.isalpha():
            continue
        cleaned.append(line)
    return "\n".join(cleaned)
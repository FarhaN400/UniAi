from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser

parser = JsonOutputParser()

notice_extraction_prompt = PromptTemplate(
    template="""You are extracting structured information from an official university notice.

You must ALWAYS return a JSON object with EXACTLY these fields, in this exact structure, regardless of the notice type:

{{
  "notice_type": "one of: Examination, Admission, Scholarship, Discipline, Administrative, Academic Calendar, General",
  "title": "short title summarizing the notice subject",
  "reference_no": "the reference/notice number if mentioned, else null",
  "issue_date": "date the notice was issued, in DD-MM-YYYY format, else null",
  "target_audience": "who this notice applies to, e.g. all students, B.Tech students, staff, else null",
  "important_dates": {{
    "start_date": "DD-MM-YYYY or null",
    "last_date": "DD-MM-YYYY or null"
  }},
  "fees": {{
    "amount": "number or null",
    "currency": "string or null",
    "type": "application | admission | registration | examination | tuition | processing | counselling | other | null"
  }},
  "action_required": "what the reader needs to do, or null if purely informational",
  "key_points": ["short bullet points capturing the main rules/facts, as an array of strings"],
  "issued_by": "name and designation of signing authority, else null",
  "summary": "2-3 sentence plain-language summary of the notice"
}}

Rules:
- Use null for any field that is genuinely not mentioned in the notice. Do NOT invent or guess values.
- Do NOT skip or rename any field, even if it doesn't apply — always include all fields with null where appropriate.
- "important_dates" refers ONLY to deadlines or event windows explicitly mentioned for an action (e.g. exam form submission, application period). Do NOT use the notice's issue/effective date here — that belongs in "issue_date" only.
- "key_points" should always be an array, even if there is only one point.
- Return ONLY the JSON object. No explanations, no markdown code fences, no extra text before or after.
- Copy all numbers, times, dates, and figures accurately as stated in the notice.
- The input text may come from OCR and could contain optical misrecognitions (for example: "JJ a.m.", "Il a.m.", or "1l a.m." for "11 a.m.", or "O" for "0"). Resolve obvious OCR character substitutions for times, dates, and numbers rather than guessing or defaulting to common assumptions like 9 a.m. or 10 a.m. Do not invent dates or times not present in the text.
- Classify a notice by its primary subject, not by isolated words. Admission cancellation, withdrawal and refund
notices belong to Admission, not Discipline.
- Set important_dates.start_date and last_date only when the notice explicitly establishes an action window, event period, or deadline. Publication dates, refund cutoff dates, and notice issue dates must not automatically become start_date or last_date. Preserve their exact meaning in key_points.
- The fees object represents fees payable by applicants or students, not refund amounts, deductions, penalties, or deposits being returned. Record these other monetary amounts with their exact purpose in key_points.
- Set fees.type ONLY when the notice explicitly identifies which kind of fee the amount represents (e.g. application fee versus admission fee). If it just says 'fee' without a category, type must be null. Never infer application fees from an admission-fee amount or from an admission-fee information URL. If multiple distinct fee types or amounts appear, do not assign one arbitrary fee to the fees object: set amount/currency/type to null, and preserve each clearly labelled payment and its amount separately in key_points.
- Even when fee information is absent, "fees" MUST remain a JSON object with "amount": null, "currency": null, and "type": null when not present. Never return "fees": null. Likewise, "important_dates" must always contain both "start_date" and "last_date", even if both values are null.

NOTICE TEXT:
{text}

{format_inst}""",
    input_variables=['text'],
    partial_variables={'format_inst': parser.get_format_instructions()}
)
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
    "currency": "string or null"
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

NOTICE TEXT:
{text}

{format_inst}""",
    input_variables=['text'],
    partial_variables={'format_inst': parser.get_format_instructions()}
)
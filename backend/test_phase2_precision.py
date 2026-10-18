"""Tests Phase 2 eligibility wording from the actual Test 3 Ollama retry."""
import ast
import re
from pathlib import Path

main_path = Path(__file__).resolve().parent / "Module4" / "main.py"
tree = ast.parse(main_path.read_text(encoding="utf-8"))
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_record_requires_both_sciences", "_eligibility_contradiction"}]
ns = {"re": re}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(main_path), "exec"), ns)
record = {"structured_data": {"key_points": ["Eligibility: Physics and Mathematics mandatory at 10+2, plus one approved additional subject. Minimum 45% (40% reserved) in the specified subjects taken together."]}}
check = ns["_eligibility_contradiction"]
assert check("Eligibility requires 10+2 with Physics and Mathematics mandatory, plus an additional permitted subject, minimum 45% aggregate (40% for reserved) in the combined subjects.", record) is None
assert check("Eligibility requires Physics and Mathematics mandatory, plus one approved subject, minimum 45% (40% reserved) in the specified subjects taken together.", record) is None
assert check("Physics, Mathematics, or other relevant subjects with 45% aggregate.", record) is not None
assert check("Physics and Mathematics with 45% overall Class 12 aggregate.", record) is not None
assert check("Physics and Mathematics with 45% aggregate.", record) is not None
print("PASS: qualified combined-subjects marks accepted; OR/overall/unqualified aggregate rejected")

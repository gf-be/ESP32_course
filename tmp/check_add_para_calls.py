import ast
from pathlib import Path

p = Path(r"F:\mechineSight\stm32\罗丹\tmp\add_deep_defense_section.py")
tree = ast.parse(p.read_text(encoding="utf-8"))
bad = []
for n in ast.walk(tree):
    if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "add_para":
        if not n.args or not (isinstance(n.args[0], ast.Name) and n.args[0].id == "doc"):
            bad.append(n.lineno)
print("bad add_para lines:", bad)

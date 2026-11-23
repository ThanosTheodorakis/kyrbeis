"""Guards for running on Windows, macOS and Linux alike."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_FILES = [p for d in ("scraper", "scripts", "tests") for p in (ROOT / d).rglob("*.py")]

# read_text()/write_text()/open() without encoding= use the OS default, which on Windows
# is not UTF-8: Greek text then reads as garbage or fails. Ruff can't always see these,
# so check the code's syntax tree directly.


def _is_binary_mode(call: ast.Call) -> bool:
    modes = [a for a in call.args[1:2]] + [k.value for k in call.keywords if k.arg == "mode"]
    return any(isinstance(m, ast.Constant) and isinstance(m.value, str) and "b" in m.value for m in modes)


def test_every_file_read_and_write_names_an_encoding():
    offenders = []
    for path in PY_FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            is_file_call = name in ("read_text", "write_text") or (isinstance(f, ast.Name) and name == "open")
            if is_file_call and not any(k.arg == "encoding" for k in node.keywords) and not _is_binary_mode(node):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, "add encoding='utf-8' at: " + ", ".join(offenders)


def test_no_hard_coded_unix_paths():
    unix_tmp = "/" + "tmp/"  # spelled out so this file doesn't match itself
    for path in PY_FILES:
        text = path.read_text(encoding="utf-8")
        assert unix_tmp not in text, f"{path.name}: use tempfile or a path under the project instead"

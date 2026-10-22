"""Rewrite every multi-line function docstring in the given .py files as one line (whitespace joined), in place.
Run bare: sbtenv/bin/python tools/one_line_docstrings.py FILE.py [FILE.py ...]; prints a count per file."""
###############
# imports and constants
###############
from __future__ import annotations
import ast, os, sys

QUOTE = '"""'

###############
# functions
###############
def spans(src: str) -> list[tuple[int, int, int, str]]:
    """(first line, last line, column, joined text) of each function docstring that spans lines and stands alone."""
    lines, out = src.split("\n"), []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or not n.body: continue
        e = n.body[0]
        if not (isinstance(e, ast.Expr) and isinstance(e.value, ast.Constant) and isinstance(e.value.value, str)): continue
        alone = not lines[e.lineno - 1][:e.col_offset].strip() and not lines[e.end_lineno - 1][e.end_col_offset:].strip()
        if e.end_lineno > e.lineno and alone: out.append((e.lineno, e.end_lineno, e.col_offset, " ".join(e.value.value.split())))
    return out

def literal(text: str) -> str:
    """Triple-quoted literal whose value is exactly text."""
    body = text.replace("\\", "\\\\").replace(QUOTE, '\\"\\"\\"')
    return QUOTE + (body[:-1] + '\\"' if body.endswith('"') else body) + QUOTE

def collapse(src: str) -> tuple[str, list[str]]:
    """Source with the docstrings from spans() on one line each, plus the joined texts in source order."""
    lines, found = src.split("\n"), spans(src)
    for first, last, col, text in sorted(found, reverse=True):
        lines[first - 1:last] = [" " * col + literal(text)]
    return "\n".join(lines), [t for _, _, _, t in sorted(found)]

def docstrings(src: str) -> set[str]:
    """Every function docstring value in src."""
    return {n.body[0].value.value for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)}

###############
# run
###############
results = [(p, *collapse(open(p).read())) for p in sys.argv[1:]]
for path, new, texts in results:
    assert set(texts) <= docstrings(new), path                         # every collapsed value round-trips through the parser
    if texts:                                                          # temp + rename: a running reader never sees half a file
        open(path + ".tmp", "w").write(new)
        os.replace(path + ".tmp", path)
    print("%s: %d docstrings collapsed, %d multi-line left" % (path, len(texts), sum("\n" in d for d in docstrings(new))))

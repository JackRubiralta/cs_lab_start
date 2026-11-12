"""Static checks on lab_start.py: no local variable may hide a module-level function
(e.g. `ok = True` inside a function that also calls ok("...") -> 'bool' is not
callable, 12 Nov 2026). Run: python3 -m unittest discover tests"""
import ast
import os
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lab_start.py")


class NoShadowing(unittest.TestCase):
    def test_locals_never_hide_module_functions(self):
        with open(SRC) as f:
            tree = ast.parse(f.read())
        module_funcs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        clashes = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            names = {a.arg for a in ast.walk(fn.args) if isinstance(a, ast.arg)}
            for n in ast.walk(fn):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    names.add(n.id)
            for name in sorted(names & module_funcs):
                clashes.append("%s() line %d assigns %r" % (getattr(fn, "name", "lambda"), fn.lineno, name))
        self.assertEqual(clashes, [])


if __name__ == "__main__":
    unittest.main()

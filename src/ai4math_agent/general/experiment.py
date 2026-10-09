"""Policy-checked, resource-bounded generated Python experiments.

This runner is deliberately NOT an OS security sandbox. Its AST policy, clean
child environment, bounded language helpers, trace budget, process timeout and
available OS memory limit reduce accidental and obvious unsafe execution. Run
only code generated for the current mathematical task. A completed computation
is always empirical, unverified evidence; it is never a proof certificate.

Supported language: assignments, functions, conditionals, loops, comprehensions,
arithmetic, indexing/slicing, selected public container methods, and safe imports
from math, itertools, fractions and collections. No classes, decorators, private
names/attributes, arbitrary imports, file/network/process access or introspection.
The operation count means Python line/call trace events plus guarded iterator and
call work units; it is not a count of exact underlying arithmetic operations.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any

POLICY_VERSION = "restricted-math-python-v1"
MAX_CODE_BYTES = 65536
MAX_OUTPUT_BYTES = 65536
MAX_RESULT_BYTES = 262144
MAX_COLLECTION_ITEMS = 100000
MAX_INT_BITS = 100000
MAX_TEXT_LENGTH = 65536
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
SECURITY_NOTICE = (
    "Policy-checked resource-bounded Python runner; not an OS security sandbox. "
    "Generated computations and embedded claims remain empirical and unverified."
)

MATH_NAMES = {
    "acos", "acosh", "asin", "asinh", "atan", "atan2", "atanh", "ceil", "comb",
    "copysign", "cos", "cosh", "degrees", "dist", "e", "erf", "erfc", "exp",
    "expm1", "fabs", "factorial", "floor", "fmod", "frexp", "fsum", "gamma",
    "gcd", "hypot", "inf", "isclose", "isfinite", "isinf", "isnan", "isqrt",
    "lcm", "ldexp", "lgamma", "log", "log10", "log1p", "log2", "modf", "nan",
    "nextafter", "perm", "pi", "pow", "prod", "radians", "remainder", "sin",
    "sinh", "sqrt", "tan", "tanh", "tau", "trunc", "ulp",
}
ITERTOOLS_NAMES = {
    "accumulate", "chain", "combinations", "combinations_with_replacement",
    "compress", "count", "cycle", "dropwhile", "filterfalse", "groupby",
    "islice", "pairwise", "permutations", "product", "repeat", "starmap", "takewhile", "zip_longest",
}
IMPORTS = {"math": MATH_NAMES, "itertools": ITERTOOLS_NAMES,
           "fractions": {"Fraction"}, "collections": {"Counter", "defaultdict", "deque"}}
CONTAINER_METHODS = {
    "append", "extend", "insert", "pop", "remove", "clear", "copy", "count", "index",
    "reverse", "sort", "add", "discard", "update", "difference", "intersection",
    "union", "symmetric_difference", "difference_update", "intersection_update",
    "symmetric_difference_update", "issubset", "issuperset", "isdisjoint", "items",
    "keys", "values", "get", "setdefault", "popitem", "appendleft", "extendleft",
    "popleft", "rotate", "lower", "upper", "strip", "lstrip", "rstrip", "split",
    "rsplit", "startswith", "endswith", "join", "replace", "find", "rfind", "isdigit",
    "isalpha", "isalnum", "as_integer_ratio", "is_integer", "conjugate", "limit_denominator",
    "elements", "most_common", "subtract", "total",
}
READ_ATTRIBUTES = {"numerator", "denominator", "real", "imag", "maxlen"}
EXCEPTIONS = {"Exception", "ValueError", "TypeError", "AssertionError", "ZeroDivisionError",
              "OverflowError", "RuntimeError", "StopIteration", "IndexError", "KeyError"}
BUILTIN_NAMES = {
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "iter",
    "len", "list", "map", "max", "min", "next", "pow", "print", "range", "reversed",
    "round", "set", "sorted", "str", "sum", "tuple", "zip",
} | EXCEPTIONS
FORBIDDEN_NAMES = {
    "open", "input", "eval", "exec", "compile", "globals", "locals", "vars", "dir", "type",
    "object", "getattr", "setattr", "delattr", "hasattr", "help", "breakpoint", "memoryview",
    "bytes", "bytearray", "classmethod", "staticmethod", "property", "super", "BaseException",
    "SystemExit", "KeyboardInterrupt", "exit", "quit", "license", "copyright", "credits",
}


class PolicyError(ValueError):
    """A program is outside the supported experiment language."""


_ALLOWED_NODES = (
    ast.Module, ast.Import, ast.ImportFrom, ast.alias, ast.Assign, ast.AnnAssign, ast.AugAssign,
    ast.Expr, ast.If, ast.For, ast.While, ast.FunctionDef, ast.Return, ast.Break, ast.Continue,
    ast.Pass, ast.Try, ast.ExceptHandler, ast.Raise, ast.Assert, ast.Lambda, ast.arguments, ast.arg,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Call,
    ast.Attribute, ast.Subscript, ast.Slice, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.IfExp, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.keyword, ast.Starred, ast.JoinedStr, ast.FormattedValue,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.LShift, ast.RShift,
    ast.BitOr, ast.BitAnd, ast.BitXor, ast.UAdd, ast.USub, ast.Not, ast.Invert, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
)


def validate_code(code: str) -> ast.Module:
    """Reject unsupported syntax before launching, and again inside the child."""
    if not isinstance(code, str) or len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise PolicyError(f"code must be UTF-8 text of at most {MAX_CODE_BYTES} bytes")
    try:
        tree = ast.parse(code, filename="<experiment>")
    except (SyntaxError, RecursionError) as exc:
        raise PolicyError(f"invalid Python syntax: {exc}") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > 10000:
        raise PolicyError("program AST is too large")
    for node in nodes:
        if not isinstance(node, _ALLOWED_NODES):
            raise PolicyError(f"unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Name):
            if node.id.startswith("_") or node.id in FORBIDDEN_NAMES:
                raise PolicyError(f"forbidden name: {node.id}")
        elif isinstance(node, ast.arg):
            if node.arg.startswith("_") or node.arg in FORBIDDEN_NAMES:
                raise PolicyError(f"forbidden parameter: {node.arg}")
        elif isinstance(node, ast.FunctionDef):
            if node.name.startswith("_") or node.name in FORBIDDEN_NAMES or node.decorator_list:
                raise PolicyError("private functions and decorators are unsupported")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in IMPORTS or alias.asname and alias.asname.startswith("_"):
                    raise PolicyError(f"unsupported import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in IMPORTS:
                raise PolicyError(f"unsupported import: {node.module}")
            for alias in node.names:
                if alias.name not in IMPORTS[node.module] or alias.asname and alias.asname.startswith("_"):
                    raise PolicyError(f"unsupported imported name: {alias.name}")
        elif isinstance(node, ast.Attribute):
            allowed = set().union(*IMPORTS.values()) | CONTAINER_METHODS | READ_ATTRIBUTES
            if node.attr.startswith("_") or node.attr not in allowed or not isinstance(node.ctx, ast.Load):
                raise PolicyError(f"unsupported attribute: {node.attr}")
        elif isinstance(node, ast.Constant):
            value = node.value
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise PolicyError("only JSON-like literal constants are supported")
            if isinstance(value, int) and value.bit_length() > MAX_INT_BITS:
                raise PolicyError("integer literal too large")
            if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
                raise PolicyError("text literal too large")
        elif isinstance(node, ast.Try):
            # Exceptions from the budget must escape, and a finally body must not
            # begin an untraced loop while such an exception is unwinding.
            if node.finalbody or any(handler.type is None for handler in node.handlers):
                raise PolicyError("bare except and finally blocks are unsupported")
        elif isinstance(node, ast.comprehension) and node.is_async:
            raise PolicyError("async comprehensions are unsupported")
    return tree


class _BudgetExceeded(BaseException):
    pass


class _ResourceExceeded(BaseException):
    pass


class _OutputExceeded(BaseException):
    pass


class _Runtime:
    def __init__(self, max_operations: int):
        self.max_operations = max_operations
        self.operations = 0

    def charge(self, amount: int = 1) -> None:
        self.operations += amount
        if self.operations > self.max_operations:
            raise _BudgetExceeded("operation/trace budget exhausted")

    def trace(self, frame, event, arg):
        if frame.f_code.co_filename == "<experiment>" and event in {"line", "call"}:
            self.charge()
        return self.trace

    def bounded_iter(self, iterable):
        for item in iterable:
            self.charge()
            yield item

    def check(self, value):
        if isinstance(value, int) and value.bit_length() > MAX_INT_BITS:
            raise _ResourceExceeded("integer bit-length limit exceeded")
        if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
            raise _ResourceExceeded("text length limit exceeded")
        if isinstance(value, (list, tuple, set, dict)) and len(value) > MAX_COLLECTION_ITEMS:
            raise _ResourceExceeded("collection length limit exceeded")
        # Fraction arithmetic uses exact integers too; avoid permitting a large
        # numerator/denominator merely because the outer object is not an int.
        if type(value).__module__ == "fractions" and (
            value.numerator.bit_length() > MAX_INT_BITS or value.denominator.bit_length() > MAX_INT_BITS
        ):
            raise _ResourceExceeded("Fraction integer bit-length limit exceeded")
        return value

    def collect(self, iterable, constructor=list):
        values = []
        weight = 0
        for item in self.bounded_iter(iterable):
            self.check(item)
            weight += max(1, len(item)) if isinstance(item, (list, tuple, set, dict, str)) else 1
            if len(values) >= MAX_COLLECTION_ITEMS or weight > MAX_COLLECTION_ITEMS:
                raise _ResourceExceeded("collection materialization limit exceeded")
            values.append(item)
        return constructor(values)

    def power(self, base, exponent, modulus=None):
        self.charge()
        self.check(base)
        self.check(exponent)
        if modulus is not None:
            self.check(modulus)
            return self.check(pow(base, exponent, modulus))
        if isinstance(exponent, int) and exponent > 0:
            if isinstance(base, int) and abs(base) > 1 and exponent * max(1, abs(base).bit_length() - 1) > MAX_INT_BITS:
                raise _ResourceExceeded("power would exceed integer bit-length limit")
            if exponent > 1000000:
                raise _ResourceExceeded("power exponent limit exceeded")
            if type(base).__module__ == "fractions" and exponent * max(
                abs(base.numerator).bit_length() - 1, base.denominator.bit_length() - 1
            ) > MAX_INT_BITS:
                raise _ResourceExceeded("Fraction power would exceed integer limit")
        return self.check(pow(base, exponent))

    def binop(self, kind: str, left, right):
        self.charge()
        self.check(left)
        self.check(right)
        if kind == "Pow":
            return self.power(left, right)
        if kind in {"LShift", "RShift"}:
            if not isinstance(right, int) or right < 0 or right > MAX_INT_BITS:
                raise _ResourceExceeded("bit shift limit exceeded")
            if kind == "LShift" and isinstance(left, int) and left.bit_length() + right > MAX_INT_BITS:
                raise _ResourceExceeded("bit shift would exceed integer limit")
        if kind == "Mult":
            collection, count = (left, right) if isinstance(right, int) else (right, left)
            if isinstance(collection, (str, list, tuple)) and isinstance(count, int):
                cap = MAX_TEXT_LENGTH if isinstance(collection, str) else MAX_COLLECTION_ITEMS
                if len(collection) * max(0, count) > cap:
                    raise _ResourceExceeded("repetition would exceed size limit")
            if isinstance(left, int) and isinstance(right, int) and left.bit_length() + right.bit_length() > MAX_INT_BITS + 1:
                raise _ResourceExceeded("multiplication would exceed integer limit")
        if kind == "Add" and isinstance(left, (str, list, tuple)) and isinstance(right, type(left)):
            cap = MAX_TEXT_LENGTH if isinstance(left, str) else MAX_COLLECTION_ITEMS
            if len(left) + len(right) > cap:
                raise _ResourceExceeded("concatenation would exceed size limit")
        import operator
        op = {"Add": operator.add, "Sub": operator.sub, "Mult": operator.mul,
              "Div": operator.truediv, "FloorDiv": operator.floordiv, "Mod": operator.mod,
              "LShift": operator.lshift, "RShift": operator.rshift, "BitOr": operator.or_,
              "BitAnd": operator.and_, "BitXor": operator.xor}[kind]
        # %-formatting has an implicit formatting interpreter; exclude it.
        if kind == "Mod" and isinstance(left, str):
            raise _ResourceExceeded("string percent formatting is unsupported")
        return self.check(op(left, right))

    def method(self, obj, name: str, *args, **kwargs):
        self.charge()
        if name in {"append", "appendleft", "insert", "add", "setdefault"} and hasattr(obj, "__len__"):
            if len(obj) >= MAX_COLLECTION_ITEMS:
                raise _ResourceExceeded("container mutation length limit exceeded")
        if name in {"extend", "extendleft", "update", "difference_update", "intersection_update", "symmetric_difference_update", "subtract"} and args:
            if isinstance(args[0], dict):
                added = self.check(args[0])
            else:
                added = self.collect(args[0])
            if hasattr(obj, "__len__") and len(obj) + len(added) > MAX_COLLECTION_ITEMS:
                raise _ResourceExceeded("container mutation length limit exceeded")
            args = (added, *args[1:])
        if name == "join" and args:
            args = (self.collect(args[0]), *args[1:])
        return self.check(getattr(obj, name)(*args, **kwargs))

    def invoke(self, function, *args, **kwargs):
        self.charge()
        return self.check(function(*args, **kwargs))


class _Guard(ast.NodeTransformer):
    def visit_BinOp(self, node):
        self.generic_visit(node)
        return ast.copy_location(ast.Call(ast.Name("_guard_binop", ast.Load()),
            [ast.Constant(type(node.op).__name__), node.left, node.right], []), node)

    def visit_AugAssign(self, node):
        self.generic_visit(node)
        if isinstance(node.target, ast.Name):
            value = ast.Call(ast.Name("_guard_binop", ast.Load()),
                             [ast.Constant(type(node.op).__name__), ast.Name(node.target.id, ast.Load()), node.value], [])
            return ast.copy_location(ast.Assign([node.target], value), node)
        if isinstance(node.target, ast.Subscript):
            # Python reads the old item before evaluating the RHS. A preparatory
            # closure preserves that order and evaluates container/index once.
            index = node.target.slice
            if isinstance(index, ast.Slice):
                index = ast.Call(ast.Name("_guard_slice", ast.Load()),
                                 [index.lower or ast.Constant(None), index.upper or ast.Constant(None),
                                  index.step or ast.Constant(None)], [])
            prepare = ast.Call(ast.Name("_guard_augprep", ast.Load()),
                               [node.target.value, index, ast.Constant(type(node.op).__name__)], [])
            return ast.copy_location(ast.Expr(ast.Call(prepare, [node.value], [])), node)
        raise PolicyError("unsupported augmented assignment target")

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute):
            return ast.copy_location(ast.Call(ast.Name("_guard_method", ast.Load()),
                [node.func.value, ast.Constant(node.func.attr), *node.args], node.keywords), node)
        return ast.copy_location(ast.Call(ast.Name("_guard_call", ast.Load()), [node.func, *node.args], node.keywords), node)


class _Module:
    """An import exposes only explicitly supported values."""
    def __init__(self, values: dict):
        self.__dict__.update(values)


def _safe_imports(runtime: _Runtime) -> dict[str, _Module]:
    import collections
    import fractions
    import itertools

    def math_function(name, function):
        def wrapped(*args, **kwargs):
            runtime.charge()
            if name in {"factorial", "comb", "perm"} and args and (not isinstance(args[0], int) or abs(args[0]) > 10000):
                raise _ResourceExceeded(f"math.{name} input limit is 10000")
            if name == "prod" and args:
                total = kwargs.get("start", 1)
                for value in runtime.bounded_iter(args[0]):
                    total = runtime.binop("Mult", total, value)
                return total
            if name in {"fsum", "dist"} and args:
                if name == "dist":
                    args = tuple(runtime.collect(arg) for arg in args)
                else:
                    args = (runtime.bounded_iter(args[0]), *args[1:])
            return runtime.check(function(*args, **kwargs))
        return wrapped

    def itertools_function(name, function):
        def wrapped(*args, **kwargs):
            runtime.charge()
            if name in {"combinations", "combinations_with_replacement", "permutations"} and args:
                pool = runtime.collect(args[0])
                width = args[1] if len(args) > 1 else kwargs.get("r", len(pool))
                if width is not None and width > 1000:
                    raise _ResourceExceeded("combinatorial tuple width limit is 1000")
                args = (pool, *args[1:])
            elif name == "product":
                repeat = kwargs.get("repeat", 1)
                if type(repeat) is not int or repeat < 0 or repeat * len(args) > 1000:
                    raise _ResourceExceeded("Cartesian product width limit is 1000")
                args = tuple(runtime.collect(arg) for arg in args)
            elif name in {"chain", "zip_longest"}:
                args = tuple(runtime.bounded_iter(arg) for arg in args)
            elif name in {"dropwhile", "filterfalse", "starmap", "takewhile"} and len(args) >= 2:
                args = (args[0], runtime.bounded_iter(args[1]), *args[2:])
            elif name == "compress" and len(args) >= 2:
                args = (runtime.bounded_iter(args[0]), runtime.bounded_iter(args[1]), *args[2:])
            elif name not in {"count", "repeat"} and args:
                args = (runtime.bounded_iter(args[0]), *args[1:])
            return function(*args, **kwargs)
        return wrapped

    def counter(iterable=None, **kwargs):
        if iterable is not None and not isinstance(iterable, dict):
            iterable = runtime.bounded_iter(iterable)
        return runtime.check(collections.Counter(iterable, **kwargs))

    def deque(iterable=(), maxlen=None):
        values = runtime.collect(iterable)
        if maxlen is not None and (type(maxlen) is not int or not 0 <= maxlen <= MAX_COLLECTION_ITEMS):
            raise _ResourceExceeded("deque maxlen limit exceeded")
        return collections.deque(values, maxlen=maxlen)

    math_values = {name: math_function(name, getattr(math, name)) if callable(getattr(math, name)) else getattr(math, name)
                   for name in MATH_NAMES if hasattr(math, name)}
    it_values = {name: itertools_function(name, getattr(itertools, name)) for name in ITERTOOLS_NAMES if hasattr(itertools, name)}
    return {"math": _Module(math_values), "itertools": _Module(it_values),
            "fractions": _Module({"Fraction": fractions.Fraction}),
            "collections": _Module({"Counter": counter, "deque": deque, "defaultdict": collections.defaultdict})}


def _environment(runtime: _Runtime) -> dict[str, Any]:
    modules = _safe_imports(runtime)

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in modules:
            raise PolicyError("unsupported runtime import")
        return modules[name]

    def safe_range(*args):
        r = range(*args)
        if len(r) > max(runtime.max_operations, MAX_COLLECTION_ITEMS):
            raise _ResourceExceeded("range length exceeds experiment limit")
        return r

    def safe_dict(iterable=(), **kwargs):
        if isinstance(iterable, dict):
            result = dict(iterable, **kwargs)
        else:
            result = dict(runtime.collect(iterable), **kwargs)
        return runtime.check(result)

    def safe_sorted(iterable, **kwargs):
        return sorted(runtime.collect(iterable), **kwargs)

    def safe_sum(iterable, start=0):
        total = start
        for item in runtime.bounded_iter(iterable):
            total = runtime.binop("Add", total, item)
        return total

    def safe_extreme(function, *args, **kwargs):
        if len(args) == 1:
            args = (runtime.bounded_iter(args[0]),)
        return function(*args, **kwargs)

    def safe_filter(function, iterable):
        for value in runtime.bounded_iter(iterable):
            if (function(value) if function is not None else value):
                yield value

    def safe_map(function, *iterables):
        return map(function, *(runtime.bounded_iter(iterable) for iterable in iterables))

    def safe_str(value=""):
        return runtime.check(str(value))

    def safe_print(*values, sep=" ", end="\n", flush=False):
        if not isinstance(sep, str) or not isinstance(end, str):
            raise TypeError("print sep/end must be strings")
        text = sep.join(safe_str(value) for value in values) + end
        sys.stdout.write(text)
        if flush:
            sys.stdout.flush()

    def augprep(container, index, kind):
        old = container[index]
        def apply(value):
            container[index] = runtime.binop(kind, old, value)
        return apply

    names = {name: getattr(builtins, name) for name in BUILTIN_NAMES}
    names.update({"__import__": safe_import, "range": safe_range, "list": lambda values=(): runtime.collect(values),
                  "tuple": lambda values=(): runtime.collect(values, tuple), "set": lambda values=(): runtime.collect(values, set),
                  "dict": safe_dict, "sorted": safe_sorted, "sum": safe_sum, "str": safe_str,
                  "pow": runtime.power, "print": safe_print,
                  "all": lambda values: all(runtime.bounded_iter(values)),
                  "any": lambda values: any(runtime.bounded_iter(values)),
                  "max": lambda *args, **kwargs: safe_extreme(max, *args, **kwargs),
                  "min": lambda *args, **kwargs: safe_extreme(min, *args, **kwargs),
                  "filter": safe_filter, "map": safe_map})
    return {"__builtins__": names, "_guard_binop": runtime.binop, "_guard_augprep": augprep,
            "_guard_slice": slice,
            "_guard_method": runtime.method, "_guard_call": runtime.invoke}


class _CappedStream:
    def __init__(self, original, maximum: int = MAX_OUTPUT_BYTES):
        self.original = original
        self.maximum = maximum
        self.count = 0

    def write(self, text):
        raw = text.encode("utf-8", "replace")
        available = max(0, self.maximum - self.count)
        if len(raw) > available:
            self.original.write(raw[:available].decode("utf-8", "ignore"))
            self.original.flush()
            self.count = self.maximum
            raise _OutputExceeded("stdout/stderr byte limit exceeded")
        self.count += len(raw)
        return self.original.write(text)

    def flush(self):
        self.original.flush()


def _os_limits(timeout_seconds: float) -> dict[str, Any]:
    """Apply child-only limits when this host supports them; report failures."""
    result = {"memory_limit_bytes": MEMORY_LIMIT_BYTES, "memory_limit_enforced": False,
              "os_cpu_limit_enforced": False}
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

            class IO(ctypes.Structure):
                _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class Extended(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            job = kernel.CreateJobObjectW(None, None)
            if not job:
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
            information = Extended()
            information.BasicLimitInformation.LimitFlags = 0x100 | 0x2
            information.BasicLimitInformation.PerProcessUserTimeLimit = max(1, math.ceil(timeout_seconds)) * 10000000
            information.ProcessMemoryLimit = MEMORY_LIMIT_BYTES
            if not kernel.SetInformationJobObject(job, 9, ctypes.byref(information), ctypes.sizeof(information)):
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
            if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
            # Retain the job handle for the child lifetime.
            globals()["_CHILD_JOB_HANDLE"] = job
        else:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
            seconds = max(1, math.ceil(timeout_seconds))
            resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
        result.update(memory_limit_enforced=True, os_cpu_limit_enforced=True)
    except Exception as exc:
        result["os_limit_error"] = str(exc)
    return result


def _result_json(value, runtime: _Runtime) -> str:
    # Validate structure with a separate bounded traversal; do not explore new
    # mathematical candidates while serializing the user's result.
    stack = [value]
    visited = 0
    while stack:
        item = stack.pop()
        visited += 1
        if visited > MAX_COLLECTION_ITEMS:
            raise _OutputExceeded("result structure is too large or cyclic")
        runtime.check(item)
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("result dictionary keys must be strings")
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
        elif item is not None and not isinstance(item, (bool, int, float, str)):
            raise ValueError("result must be JSON data; explicitly convert Fraction/set/iterator values")
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(text.encode("utf-8")) > MAX_RESULT_BYTES:
        raise _OutputExceeded("serialized result byte limit exceeded")
    return text


def _payload(execution_status: str, result=None, operations=0, error=None, limits=None) -> dict[str, Any]:
    return {"execution_status": execution_status, "status": "empirical_unverified",
            "evidence_strength": "empirical_unverified", "conclusion_status": "unverified",
            "user_claims_trusted": False, "result": result, "operations": operations,
            "error": error, "policy_version": POLICY_VERSION, "security_notice": SECURITY_NOTICE,
            "limits": limits or {}}


def _child(code_path: str, output_dir: str, timeout_seconds: float, max_operations: int) -> None:
    directory = Path(output_dir)
    limits = _os_limits(timeout_seconds)
    (directory / "limits.json").write_text(json.dumps(limits), encoding="utf-8")
    sys.setrecursionlimit(400)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    original_stdout, original_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _CappedStream(original_stdout), _CappedStream(original_stderr)
    runtime = _Runtime(max_operations)
    payload = _payload("runtime_error", limits=limits)
    try:
        code = Path(code_path).read_text(encoding="utf-8")
        tree = ast.fix_missing_locations(_Guard().visit(validate_code(code)))
        namespace = _environment(runtime)
        compiled = compile(tree, "<experiment>", "exec")
        sys.settrace(runtime.trace)
        exec(compiled, namespace, namespace)
        sys.settrace(None)
        if "result" not in namespace:
            raise ValueError("experiment must assign its JSON output to result")
        result = json.loads(_result_json(namespace["result"], runtime))
        payload = _payload("completed", result, runtime.operations, limits=limits)
    except _BudgetExceeded as exc:
        payload = _payload("operation_limit", operations=runtime.operations, error=str(exc), limits=limits)
    except _ResourceExceeded as exc:
        payload = _payload("resource_limit", operations=runtime.operations, error=str(exc), limits=limits)
    except _OutputExceeded as exc:
        payload = _payload("output_limit", operations=runtime.operations, error=str(exc), limits=limits)
    except BaseException as exc:
        payload = _payload("runtime_error", operations=runtime.operations, error=f"{type(exc).__name__}: {exc}", limits=limits)
        try:
            traceback.print_exc(limit=5)
        except _OutputExceeded:
            pass
    finally:
        sys.settrace(None)
        sys.stdout, sys.stderr = original_stdout, original_stderr
        (directory / "result.json").write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def run_experiment(code: str, output_dir, timeout_seconds: float = 10, max_operations: int = 200000) -> dict[str, Any]:
    """Execute generated computation and save original code, streams and result.

    Timeout applies to the child process including startup/imports. The parent
    validates inputs and AST before launch; the child validates AST again. Even
    user results claiming a theorem have top-level status empirical_unverified.
    """
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be finite and in (0, 60]")
    if type(max_operations) is not int or not 1 <= max_operations <= 1000000:
        raise ValueError("max_operations must be an integer in 1..1000000")
    started = time.perf_counter()
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    code_path = directory / "code.py"
    if not isinstance(code, str):
        raise ValueError("code must be text")
    encoded_code = code.encode("utf-8")
    code_path.write_text(encoded_code[:MAX_CODE_BYTES].decode("utf-8", "ignore"), encoding="utf-8")
    stdout = stderr = ""
    payload = None
    try:
        validate_code(code)
    except PolicyError as exc:
        payload = _payload("rejected", error=str(exc))
    if payload is None:
        # Reusing a destination must not turn a previous child result into the
        # evidence for this execution.
        for stale in ("result.json", "limits.json"):
            (directory / stale).unlink(missing_ok=True)
        environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ}
        command = [sys.executable, "-I", "-u", str(Path(__file__).resolve()), "--child",
                   str(code_path), str(directory), str(timeout_seconds), str(max_operations)]
        process = subprocess.Popen(command, cwd=directory, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", shell=False)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
        limits_path = directory / "limits.json"
        limits = json.loads(limits_path.read_text(encoding="utf-8")) if limits_path.exists() else {}
        if timed_out:
            payload = _payload("time_limit", operations=None, error="child process wall-time limit exceeded", limits=limits)
        elif process.returncode != 0 or not (directory / "result.json").exists():
            payload = _payload("resource_limit" if process.returncode else "runtime_error", operations=None,
                               error=f"child terminated without a result (exit {process.returncode})", limits=limits)
        else:
            try:
                payload = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                payload = _payload("runtime_error", error=f"invalid child result: {exc}", limits=limits)
    # The child streams are capped too. Apply a second independent parent cap.
    stdout = stdout.encode("utf-8")[:MAX_OUTPUT_BYTES].decode("utf-8", "ignore")
    stderr = stderr.encode("utf-8")[:MAX_OUTPUT_BYTES].decode("utf-8", "ignore")
    # Binary writes preserve the byte cap on Windows too (no LF-to-CRLF growth).
    (directory / "stdout.txt").write_bytes(stdout.encode("utf-8"))
    (directory / "stderr.txt").write_bytes(stderr.encode("utf-8"))
    payload.update(timeout_seconds=float(timeout_seconds), max_operations=max_operations,
                   elapsed_seconds=time.perf_counter() - started,
                   code_original_bytes=len(encoded_code), code_saved_truncated=len(encoded_code) > MAX_CODE_BYTES,
                   code_original_sha256=hashlib.sha256(encoded_code).hexdigest())
    (directory / "result.json").write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    artifacts = {name: {"path": str(directory / name), "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest()}
                 for name in ("code.py", "stdout.txt", "stderr.txt", "result.json")}
    if (directory / "limits.json").exists():
        artifacts["limits.json"] = {"path": str(directory / "limits.json"), "sha256": hashlib.sha256((directory / "limits.json").read_bytes()).hexdigest()}
    return {**payload, "artifacts": artifacts}


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--child":
    _child(sys.argv[2], sys.argv[3], float(sys.argv[4]), int(sys.argv[5]))

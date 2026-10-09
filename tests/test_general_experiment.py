"""Generated algorithm execution, policy limits, and non-proof evidence status."""

import hashlib
import json
from pathlib import Path
import time

import pytest

from ai4math_agent.general.experiment import MAX_OUTPUT_BYTES, run_experiment


def test_generated_number_theory_algorithm_and_fraction_arithmetic(tmp_path):
    code = '''from math import isqrt
from fractions import Fraction

def is_prime(n):
    if n < 2:
        return False
    for divisor in range(2, isqrt(n) + 1):
        if n % divisor == 0:
            return False
    return True

primes = [n for n in range(2, 101) if is_prime(n)]
harmonic = sum(Fraction(1, p) for p in primes[:5])
print("prime_count", len(primes))
result = {"primes": primes, "harmonic": str(harmonic), "status": "proved"}
'''
    outcome = run_experiment(code, tmp_path)
    assert outcome["execution_status"] == "completed", outcome
    assert outcome["result"]["primes"] == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
    assert outcome["result"]["harmonic"] == "2927/2310"
    assert outcome["status"] == outcome["evidence_strength"] == "empirical_unverified"
    assert outcome["conclusion_status"] == "unverified"
    assert not outcome["user_claims_trusted"]
    assert "not an OS security sandbox" in outcome["security_notice"]
    assert (tmp_path / "stdout.txt").read_text() == "prime_count 25\n"
    for artifact in outcome["artifacts"].values():
        assert hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]
    assert json.loads((tmp_path / "result.json").read_text())["result"] == outcome["result"]


def test_itertools_collections_methods_and_augmented_index(tmp_path):
    code = '''import itertools
from collections import Counter, defaultdict, deque
counts = Counter(sum(pair) for pair in itertools.product(range(3), repeat=2))
groups = defaultdict(list)
for pair in itertools.combinations(range(5), 2):
    groups[sum(pair) % 2].append(list(pair))
queue = deque([1, 2])
queue.appendleft(0)
values = [1, 2, 3]
values[1] += 10
result = {"counts": {str(k): v for k, v in counts.items()}, "group_sizes": [len(groups[0]),len(groups[1])], "queue": list(queue), "values": values}
'''
    outcome = run_experiment(code, tmp_path)
    assert outcome["execution_status"] == "completed", outcome
    assert outcome["result"] == {"counts": {"0": 1, "1": 2, "2": 3, "3": 2, "4": 1},
                                 "group_sizes": [4, 6], "queue": [0, 1, 2], "values": [1, 12, 3]}


def test_augmented_assignment_preserves_python_evaluation_order_and_slices(tmp_path):
    code = '''values = [1, 2, 3]
def change():
    values[0] = 9
    return 1
values[0] += change()
values[1:2] += [4]
result = values
'''
    outcome = run_experiment(code, tmp_path)
    assert outcome["execution_status"] == "completed", outcome
    assert outcome["result"] == [2, 2, 4, 3]


@pytest.mark.parametrize("code", [
    "import os\nresult = 1", "from pathlib import Path\nresult = 1",
    "import subprocess\nresult = 1", "import socket\nresult = 1",
    "result = open('secret.txt').read()", "result = getattr(1, '__class__')",
    "result = (1).__class__", "result = eval('1+1')", "result = globals()",
    "result = '{x.__class__}'.format(x=1)", "class X:\n    pass\nresult=1",
    "try:\n    result = 1\nexcept:\n    result = 2",
    "try:\n    result = 1\nfinally:\n    result = 2",
    "try:\n    result = 1\nexcept BaseException:\n    result = 2",
])
def test_unsafe_or_unsupported_code_is_rejected_before_child(code, tmp_path):
    outcome = run_experiment(code, tmp_path)
    assert outcome["execution_status"] == "rejected"
    assert outcome["result"] is None
    assert outcome["operations"] == 0
    assert not (tmp_path / "limits.json").exists()
    assert (tmp_path / "code.py").read_text() == code


def test_trace_budget_aborts_loop_and_cannot_be_caught_by_exception(tmp_path):
    code = '''try:
    value = 0
    while True:
        value += 1
except Exception:
    result = {"caught": True}
'''
    outcome = run_experiment(code, tmp_path, max_operations=100)
    assert outcome["execution_status"] == "operation_limit", outcome
    assert outcome["operations"] == 101
    assert outcome["result"] is None


def test_wall_timeout_terminates_child_including_startup(tmp_path):
    started = time.perf_counter()
    outcome = run_experiment("while True:\n    pass", tmp_path, timeout_seconds=0.01, max_operations=1000000)
    assert outcome["execution_status"] == "time_limit", outcome
    assert time.perf_counter() - started < 3
    assert outcome["operations"] is None
    assert (tmp_path / "result.json").exists()


@pytest.mark.parametrize("expression", ["all(itertools.repeat(True))",
                                       "next(itertools.dropwhile(bool, itertools.repeat(1)))",
                                       "next(filter(None, itertools.repeat(0)))",
                                       "min(itertools.count())"])
def test_native_iterator_consumption_is_also_operation_bounded(expression, tmp_path):
    outcome = run_experiment("import itertools\nresult = " + expression, tmp_path, max_operations=1000)
    assert outcome["execution_status"] == "operation_limit", outcome
    assert outcome["operations"] == 1001


@pytest.mark.parametrize("expression", [
    "2 ** 1000000000", "pow(2, 1000000000)", "[0] * 1000000000",
    "'a' * 1000000000", "1 << 1000000000", "list(range(1000000000))",
])
def test_memory_expansion_is_guarded_before_allocation(expression, tmp_path):
    outcome = run_experiment("result = " + expression, tmp_path)
    assert outcome["execution_status"] == "resource_limit", outcome
    assert outcome["elapsed_seconds"] < 3
    assert outcome["result"] is None


def test_stdout_and_result_size_limits(tmp_path):
    output = run_experiment("for j in range(100):\n    print('x' * 2000)\nresult = 1", tmp_path / "stdout")
    assert output["execution_status"] == "output_limit", output
    assert (tmp_path / "stdout" / "stdout.txt").stat().st_size <= MAX_OUTPUT_BYTES
    result = run_experiment("result = [123456789] * 30000", tmp_path / "result")
    assert result["execution_status"] == "output_limit", result
    assert result["result"] is None


def test_errors_missing_result_and_cyclic_result_are_retained(tmp_path):
    outcome = run_experiment("result = 1 / 0", tmp_path / "error")
    assert outcome["execution_status"] == "runtime_error"
    assert "ZeroDivisionError" in outcome["error"]
    assert "ZeroDivisionError" in (tmp_path / "error" / "stderr.txt").read_text()
    missing = run_experiment("value = 1", tmp_path / "missing")
    assert missing["execution_status"] == "runtime_error"
    assert "assign" in missing["error"]
    cyclic = run_experiment("result = []\nresult.append(result)", tmp_path / "cyclic")
    assert cyclic["execution_status"] == "output_limit"


def test_reusing_directory_does_not_reuse_old_result(tmp_path):
    first = run_experiment("result = {'value': 7}", tmp_path)
    assert first["execution_status"] == "completed"
    second = run_experiment("while True:\n    pass", tmp_path, timeout_seconds=0.01)
    assert second["execution_status"] == "time_limit"
    assert second["result"] is None


@pytest.mark.parametrize("kwargs", [{"max_operations": 0}, {"max_operations": True},
                                    {"timeout_seconds": 0}, {"timeout_seconds": float("inf")}])
def test_invalid_execution_limits_are_not_silently_accepted(kwargs, tmp_path):
    with pytest.raises(ValueError):
        run_experiment("result = 1", tmp_path, **kwargs)

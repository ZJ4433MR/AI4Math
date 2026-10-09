"""Isolated, time-bounded mathematical tool entry point (no generated Python here)."""
import json
import sys
from .tools import math_dispatch


def main():
    try:
        payload = json.load(sys.stdin)
        result = math_dispatch(payload["name"], payload["arguments"])
    except Exception as exc:
        result = {"status": "tool_error", "error": str(exc), "operations": 0}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

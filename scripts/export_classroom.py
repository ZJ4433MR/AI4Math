"""Export the verified classroom archive as a single offline HTML file."""
import argparse
import json
from pathlib import Path

from ai4math_agent.general.showcase import load_showcase


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "ai4math_agent" / "general" / "showcase.html"
ARCHIVE_MARKER = "null /*__CLASSROOM_ARCHIVE__*/"
TOKEN_MARKER = "__SHOWCASE_TOKEN__"


def export_classroom(output: Path) -> None:
    archive = load_showcase(ROOT)
    if not archive["profiles"] or not archive["rounds"]:
        raise ValueError("The verified energy profiles and research rounds are both required.")
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(ARCHIVE_MARKER) != 1 or template.count(TOKEN_MARKER) != 1:
        raise ValueError("The showcase template is missing its archive or token marker.")
    if output.resolve() == TEMPLATE.resolve():
        raise ValueError("Choose a different output file from the live showcase template.")

    # A string containing </script> must remain data even in an inline script.
    payload = json.dumps(archive, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    payload = payload.replace("<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026")
    page = template.replace(TOKEN_MARKER, "null").replace(ARCHIVE_MARKER, payload)
    policy = """<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'">"""
    page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + policy, 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=ROOT / "reports" / "AI4Math-classroom-offline.html")
    args = parser.parse_args()
    export_classroom(args.output)
    print(args.output.resolve())

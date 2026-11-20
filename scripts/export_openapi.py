import argparse
import json
from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Export DonkE's HTTP API from FastAPI")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "docs/api/openapi.json"
    app = create_app(Settings(_env_file=None))
    content = (
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            parser.exit(
                1, "Run python -m scripts.export_openapi to update the contract\n"
            )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

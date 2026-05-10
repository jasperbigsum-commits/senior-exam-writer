from __future__ import annotations

import json
from pathlib import Path

from senior_exam_writer_lib.runtime import init_runtime_layout


def main() -> None:
    manifest = init_runtime_layout(Path("./exam_evidence.sqlite"))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

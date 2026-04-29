from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_correction_log(correction_log: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(correction_log, ensure_ascii=False, indent=2), encoding="utf-8")


def write_final_delivery_audit(delivery_audit: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(delivery_audit, ensure_ascii=False, indent=2), encoding="utf-8")

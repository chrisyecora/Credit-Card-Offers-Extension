"""Write a scraper result and its capture metadata as local artifacts."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def metadata_path(output: Path) -> Path:
    return output.with_name(output.name + ".meta.json")


def write_capture(
    output: Path, offers: list[dict], bank_slug: str, warnings: list[str] | None = None
) -> None:
    if not offers:
        raise ValueError("An empty capture cannot be published")
    payload = (json.dumps(offers, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    metadata = {
        "version": 1,
        "bank_slug": bank_slug,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "offer_count": len(offers),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "warnings": warnings or [],
    }
    data_temporary = output.with_name(output.name + ".tmp")
    metadata_file = metadata_path(output)
    metadata_temporary = metadata_file.with_name(metadata_file.name + ".tmp")
    # An interrupted write leaves either no metadata or a hash mismatch.
    metadata_file.unlink(missing_ok=True)
    data_temporary.write_bytes(payload)
    data_temporary.replace(output)
    metadata_temporary.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    metadata_temporary.replace(metadata_file)


def write_unverified_capture(output: Path, offers: list[dict]) -> None:
    """Keep manually saved source responses inspectable, but not publishable."""
    metadata_path(output).unlink(missing_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(offers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)

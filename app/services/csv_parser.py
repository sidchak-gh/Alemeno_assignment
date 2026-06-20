"""
csv_parser.py — Initial CSV ingestion and validation.
Returns raw rows as dicts for the cleaner to process.
"""
import csv
import io
from pathlib import Path


class CSVValidationError(Exception):
    pass


REQUIRED_COLUMNS = {
    "txn_id", "date", "merchant", "amount",
    "currency", "status", "category", "account_id", "notes",
}


def parse_csv_bytes(content: bytes) -> tuple[list[dict], int]:
    """
    Parse raw CSV bytes.
    Returns (rows_as_dicts, raw_row_count).
    """
    try:
        text = content.decode("utf-8-sig") 
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise CSVValidationError("CSV file is empty or has no header row.")

    headers = {h.strip().lower() for h in reader.fieldnames if h}
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise CSVValidationError(
            f"CSV is missing required columns: {', '.join(sorted(missing))}"
        )

    rows = []
    for row in reader:
        # Normalise keys to lowercase stripped
        clean_row = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}
        rows.append(clean_row)

    if not rows:
        raise CSVValidationError("CSV file contains no data rows.")

    return rows, len(rows)


def parse_csv_file(path: Path) -> tuple[list[dict], int]:
    """Convenience wrapper that reads from disk."""
    return parse_csv_bytes(path.read_bytes())

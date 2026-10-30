"""Safely replace local usage caches without truncating prior history."""
import json
import math
import os
import pathlib
import re
import sys
import tempfile


def write_bytes(destination, data):
    destination = pathlib.Path(destination)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}-", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


COMPONENTS = ("inputTokens", "outputTokens", "cacheReadTokens", "cacheCreationTokens")


def validate_cursor(value):
    if not isinstance(value, dict) or not isinstance(value.get("monthly"), list) or not isinstance(value.get("totals"), dict):
        raise ValueError("Cursor cache has invalid structure")
    months = {}

    def validate_counts(row):
        if not isinstance(row, dict):
            raise ValueError("Cursor cache contains invalid row")
        for key in COMPONENTS + ("totalTokens",):
            count = row.get(key)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("Cursor cache contains invalid token count")
        if row["totalTokens"] != sum(row[k] for k in COMPONENTS):
            raise ValueError("Cursor cache token components do not add up")

    def validate_cost(cost):
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            raise ValueError("Cursor cache contains invalid cost")

    totals = value["totals"]
    validate_counts(totals)
    for row in value["monthly"]:
        validate_counts(row)
        month = row.get("month")
        if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) or month in months:
            raise ValueError("Cursor cache contains invalid or duplicate month")
        models = row.get("models")
        if not isinstance(models, dict):
            raise ValueError("Cursor cache contains invalid models")
        for model in models.values():
            validate_counts(model)
            validate_cost(model.get("cost"))
        for key in COMPONENTS + ("totalTokens",):
            if row[key] != sum(model[key] for model in models.values()):
                raise ValueError("Cursor cache model components do not add up")
        cost = row.get("totalCost")
        validate_cost(cost)
        months[month] = (row["totalTokens"], cost)
    for key in COMPONENTS + ("totalTokens",):
        if totals[key] != sum(row[key] for row in value["monthly"]):
            raise ValueError("Cursor cache monthly components do not add up")
    validate_cost(totals.get("totalCost"))
    if not math.isclose(totals["totalCost"], sum(row["totalCost"] for row in value["monthly"]), rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError("Cursor cache monthly costs do not add up")
    return months


def copy_cursor(source, destination):
    data = pathlib.Path(source).read_bytes()
    parsed = json.loads(data)
    new_months = validate_cursor(parsed)
    destination = pathlib.Path(destination)
    if destination.exists():
        old_months = validate_cursor(json.loads(destination.read_bytes()))
        if any(new_months.get(month, (0, 0))[0] < count
               or (month not in new_months and cost > 0)
               for month, (count, cost) in old_months.items()):
            raise ValueError("Cursor scan would reduce saved monthly tokens")
    write_bytes(destination, data)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--validate":
            validate_cursor(json.loads(pathlib.Path(sys.argv[2]).read_bytes()))
        elif len(sys.argv) == 3:
            copy_cursor(sys.argv[1], sys.argv[2])
        else:
            raise ValueError("usage: atomic_cache.py <cursor scan> <cache>")
    except (OSError, ValueError) as exc:
        print(f"Cursor cache not replaced: {exc}", file=sys.stderr)
        sys.exit(1)

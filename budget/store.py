from __future__ import annotations

import calendar
import csv
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


FREQUENCY_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def iso_today() -> str:
    return date.today().isoformat()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def money(value: object) -> float:
    return round(float(value), 2)


def add_months(day: date, count: int) -> date:
    month_index = day.month - 1 + count
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def occurrences_between(start: date, frequency: str, window_start: date, window_end: date) -> Iterable[date]:
    if start > window_end:
        return

    if frequency in {"weekly", "biweekly"}:
        step = 7 if frequency == "weekly" else 14
        current = start
        if current < window_start:
            jumps = max(0, (window_start - current).days // step)
            current += timedelta(days=jumps * step)
            while current < window_start:
                current += timedelta(days=step)
        while current <= window_end:
            yield current
            current += timedelta(days=step)
        return

    month_step = FREQUENCY_MONTHS[frequency]
    index = 0
    current = start
    while current < window_start:
        index += 1
        current = add_months(start, index * month_step)
    while current <= window_end:
        yield current
        index += 1
        current = add_months(start, index * month_step)


def nth_weekday_of_month(year: int, month: int, weekday: int, ordinal: int) -> date:
    """Return an nth weekday; ordinal -1 means the last weekday of the month."""
    if weekday not in range(7) or ordinal not in {-1, 1, 2, 3, 4}:
        raise ValueError("Invalid weekday schedule")
    if ordinal == -1:
        last = date(year, month, calendar.monthrange(year, month)[1])
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (ordinal - 1) * 7)


def scheduled_occurrences(
    start: date,
    frequency: str,
    schedule_type: str,
    weekday: int | None,
    ordinal: int | None,
    window_start: date,
    window_end: date,
) -> Iterable[date]:
    effective_start = max(start, window_start)
    if schedule_type == "interval":
        yield from occurrences_between(start, frequency, window_start, window_end)
        return
    if weekday is None or weekday not in range(7):
        raise ValueError("A weekday is required for this schedule")
    if schedule_type == "weekday":
        current = effective_start + timedelta(days=(weekday - effective_start.weekday()) % 7)
        while current <= window_end:
            yield current
            current += timedelta(days=7)
        return
    if schedule_type == "nth_weekday":
        if ordinal not in {-1, 1, 2, 3, 4}:
            raise ValueError("An ordinal week is required for this schedule")
        month_cursor = date(effective_start.year, effective_start.month, 1)
        while month_cursor <= window_end:
            occurrence = nth_weekday_of_month(month_cursor.year, month_cursor.month, weekday, ordinal)
            if effective_start <= occurrence <= window_end:
                yield occurrence
            month_cursor = add_months(month_cursor, 1)
        return
    raise ValueError("Invalid schedule type")


@dataclass
class Store:
    path: Path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, sample_csv: Path | None = None) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recurring_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('income', 'expense')),
                    amount REAL NOT NULL CHECK(amount >= 0),
                    frequency TEXT NOT NULL CHECK(frequency IN ('weekly', 'biweekly', 'monthly', 'quarterly', 'yearly')),
                    schedule_type TEXT NOT NULL DEFAULT 'interval',
                    weekday INTEGER,
                    ordinal INTEGER,
                    start_date TEXT NOT NULL,
                    end_date TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('income', 'expense')),
                    amount REAL NOT NULL CHECK(amount >= 0),
                    date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned', 'posted')),
                    note TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_key TEXT UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            recurring_columns = {row["name"] for row in db.execute("PRAGMA table_info(recurring_items)")}
            if "schedule_type" not in recurring_columns:
                db.execute("ALTER TABLE recurring_items ADD COLUMN schedule_type TEXT NOT NULL DEFAULT 'interval'")
            if "weekday" not in recurring_columns:
                db.execute("ALTER TABLE recurring_items ADD COLUMN weekday INTEGER")
            if "ordinal" not in recurring_columns:
                db.execute("ALTER TABLE recurring_items ADD COLUMN ordinal INTEGER")
            defaults = {
                "current_balance": "0",
                "balance_as_of": iso_today(),
                "sample_imported": "0",
            }
            for key, value in defaults.items():
                db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))

        if sample_csv and sample_csv.exists():
            self.import_sample(sample_csv)

    def settings(self) -> dict:
        with self.connect() as db:
            values = {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM settings")}
        return {
            "current_balance": money(values.get("current_balance", 0)),
            "balance_as_of": values.get("balance_as_of", iso_today()),
            "sample_imported": values.get("sample_imported") == "1",
        }

    def update_settings(self, payload: dict) -> dict:
        balance = money(payload["current_balance"])
        as_of = parse_date(payload["balance_as_of"]).isoformat()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('current_balance', ?)", (str(balance),))
            db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('balance_as_of', ?)", (as_of,))
        return self.settings()

    def list_items(self, table: str) -> list[dict]:
        if table not in {"recurring_items", "transactions"}:
            raise ValueError("Invalid table")
        order = "start_date, name" if table == "recurring_items" else "date, name"
        with self.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]

    def save_item(self, table: str, payload: dict, item_id: int | None = None) -> dict:
        if table == "recurring_items":
            schedule_type = validate_choice(
                payload.get("schedule_type", "interval"),
                {"interval", "weekday", "nth_weekday"},
                "schedule type",
            )
            weekday = validate_optional_int(payload.get("weekday"), range(7), "weekday") if schedule_type != "interval" else None
            ordinal = validate_optional_int(payload.get("ordinal"), {-1, 1, 2, 3, 4}, "ordinal") if schedule_type == "nth_weekday" else None
            if schedule_type != "interval" and weekday is None:
                raise ValueError("A weekday is required for this schedule")
            if schedule_type == "nth_weekday" and ordinal is None:
                raise ValueError("An ordinal week is required for this schedule")
            frequency = payload.get("frequency", "monthly")
            if schedule_type == "weekday":
                frequency = "weekly"
            elif schedule_type == "nth_weekday":
                frequency = "monthly"
            values = {
                "name": clean_name(payload.get("name")),
                "kind": validate_choice(payload.get("kind"), {"income", "expense"}, "kind"),
                "amount": validate_amount(payload.get("amount")),
                "frequency": validate_choice(frequency, {"weekly", "biweekly", "monthly", "quarterly", "yearly"}, "frequency"),
                "schedule_type": schedule_type,
                "weekday": weekday,
                "ordinal": ordinal,
                "start_date": parse_date(payload.get("start_date", "")).isoformat(),
                "end_date": parse_date(payload["end_date"]).isoformat() if payload.get("end_date") else None,
                "active": 1 if payload.get("active", True) else 0,
                "note": str(payload.get("note", "")).strip()[:500],
            }
            fields = list(values)
        elif table == "transactions":
            values = {
                "name": clean_name(payload.get("name")),
                "kind": validate_choice(payload.get("kind"), {"income", "expense"}, "kind"),
                "amount": validate_amount(payload.get("amount")),
                "date": parse_date(payload.get("date", "")).isoformat(),
                "status": validate_choice(payload.get("status", "planned"), {"planned", "posted"}, "status"),
                "note": str(payload.get("note", "")).strip()[:500],
                "source": "manual",
                "source_key": None,
            }
            fields = list(values)
        else:
            raise ValueError("Invalid item type")

        with self.connect() as db:
            if item_id is None:
                placeholders = ", ".join("?" for _ in fields)
                cursor = db.execute(
                    f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({placeholders})",
                    tuple(values[field] for field in fields),
                )
                item_id = cursor.lastrowid
            else:
                assignments = ", ".join(f"{field} = ?" for field in fields)
                cursor = db.execute(
                    f"UPDATE {table} SET {assignments} WHERE id = ?",
                    (*[values[field] for field in fields], item_id),
                )
                if cursor.rowcount == 0:
                    raise KeyError("Item not found")
            row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
            return dict(row)

    def delete_item(self, table: str, item_id: int) -> None:
        if table not in {"recurring_items", "transactions"}:
            raise ValueError("Invalid item type")
        with self.connect() as db:
            cursor = db.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
            if cursor.rowcount == 0:
                raise KeyError("Item not found")

    def projection(self, start: date, weeks: int = 12) -> dict:
        weeks = max(1, min(52, weeks))
        end = start + timedelta(days=weeks * 7 - 1)
        settings = self.settings()
        events: list[dict] = []

        with self.connect() as db:
            recurring = db.execute("SELECT * FROM recurring_items WHERE active = 1").fetchall()
            transactions = db.execute(
                "SELECT * FROM transactions WHERE date BETWEEN ? AND ? ORDER BY date, id",
                (start.isoformat(), end.isoformat()),
            ).fetchall()

        for row in recurring:
            item_start = parse_date(row["start_date"])
            item_end = min(end, parse_date(row["end_date"])) if row["end_date"] else end
            if item_end < start:
                continue
            for occurrence in scheduled_occurrences(
                item_start,
                row["frequency"],
                row["schedule_type"],
                row["weekday"],
                row["ordinal"],
                start,
                item_end,
            ):
                events.append(event_from_row(row, occurrence, "recurring"))

        for row in transactions:
            events.append(event_from_row(row, parse_date(row["date"]), "transaction"))

        events.sort(key=lambda item: (item["date"], 0 if item["kind"] == "income" else 1, item["name"].lower()))
        running = money(settings["current_balance"])
        lowest = running
        next_income = next((event for event in events if event["kind"] == "income"), None)
        balance_before_next_income = running
        for event in events:
            if next_income and event is next_income:
                break
            running += event["signed_amount"]
            balance_before_next_income = money(running)

        running = money(settings["current_balance"])
        week_rows = []
        for index in range(weeks):
            week_start = start + timedelta(days=index * 7)
            week_end = week_start + timedelta(days=6)
            week_events = [event for event in events if week_start.isoformat() <= event["date"] <= week_end.isoformat()]
            income = money(sum(event["amount"] for event in week_events if event["kind"] == "income"))
            expenses = money(sum(event["amount"] for event in week_events if event["kind"] == "expense"))
            opening = running
            running = money(running + income - expenses)
            lowest = min(lowest, running)
            week_rows.append({
                "start": week_start.isoformat(),
                "end": week_end.isoformat(),
                "opening_balance": opening,
                "income": income,
                "expenses": expenses,
                "closing_balance": running,
                "events": week_events,
            })

        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "starting_balance": settings["current_balance"],
            "ending_balance": running,
            "lowest_balance": money(lowest),
            "next_income": next_income,
            "balance_before_next_income": balance_before_next_income,
            "weeks": week_rows,
        }

    def import_sample(self, path: Path) -> dict:
        with self.connect() as db:
            imported = db.execute("SELECT value FROM settings WHERE key = 'sample_imported'").fetchone()
            if imported and imported[0] == "1":
                return {"imported": 0, "skipped": True}

        with path.open(newline="", encoding="utf-8-sig") as source:
            rows = list(csv.reader(source))
        if len(rows) < 4:
            return {"imported": 0, "skipped": True}
        date_columns = []
        previous_month = 0
        year = date.today().year
        for index in range(0, len(rows[0]), 2):
            label = rows[0][index].strip() if index < len(rows[0]) else ""
            if not label and index + 1 < len(rows[0]):
                label = rows[0][index + 1].strip()
                if label:
                    index += 1
            parsed = parse_sheet_date(label, year)
            if parsed:
                if previous_month and parsed.month < previous_month:
                    year += 1
                    parsed = parsed.replace(year=year)
                previous_month = parsed.month
                date_columns.append((index, parsed))

        # The first row begins with an empty cell, so detect every non-empty date directly.
        date_columns = []
        previous_month = 0
        year = date.today().year
        for index, label in enumerate(rows[0]):
            parsed = parse_sheet_date(label.strip(), year)
            if not parsed:
                continue
            if previous_month and parsed.month < previous_month:
                year += 1
                parsed = parsed.replace(year=year)
            previous_month = parsed.month
            date_columns.append((index, parsed))

        imported_count = 0
        with self.connect() as db:
            if date_columns and len(rows) > 1:
                first_col, first_date = date_columns[0]
                initial = parse_sheet_amount(rows[1][first_col] if first_col < len(rows[1]) else "")
                # Prefer the sheet's calculated remainder when present; it represents
                # spendable cash after that week's listed expenses.
                for row in rows:
                    if first_col > 0 and first_col < len(row) and row[first_col - 1].strip().lower() == "left":
                        remainder = parse_sheet_amount(row[first_col])
                        if remainder is not None:
                            initial = remainder
                        break
                if initial is not None:
                    db.execute("UPDATE settings SET value = ? WHERE key = 'current_balance'", (str(initial),))
                    db.execute("UPDATE settings SET value = ? WHERE key = 'balance_as_of'", (first_date.isoformat(),))

            for amount_col, sheet_date in date_columns:
                name_col = amount_col - 1
                for row_index in range(3, max(3, len(rows) - 2)):
                    row = rows[row_index]
                    if name_col < 0 or amount_col >= len(row):
                        continue
                    name = row[name_col].strip()
                    amount_text = row[amount_col].strip()
                    if not name or name.lower() in {"expense subtotal", "left", "expenses"}:
                        continue
                    amount = parse_sheet_amount(amount_text)
                    if amount is None:
                        continue
                    key = f"winter-26-27:{sheet_date.isoformat()}:{row_index}:{name.lower()}"
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO transactions
                           (name, kind, amount, date, status, note, source, source_key)
                           VALUES (?, 'expense', ?, ?, 'planned', ?, 'sample_csv', ?)""",
                        (name, amount, sheet_date.isoformat(), "Imported from the private winter planning sheet", key),
                    )
                    imported_count += cursor.rowcount
            db.execute("UPDATE settings SET value = '1' WHERE key = 'sample_imported'")
        return {"imported": imported_count, "skipped": False}


def clean_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("Name is required")
    return name[:100]


def validate_choice(value: object, choices: set[str], field: str) -> str:
    if value not in choices:
        raise ValueError(f"Invalid {field}")
    return str(value)


def validate_amount(value: object) -> float:
    amount = money(value)
    if amount <= 0 or amount > 100_000_000:
        raise ValueError("Amount must be greater than zero")
    return amount


def validate_optional_int(value: object, choices: Iterable[int], field: str) -> int | None:
    if value in {None, ""}:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field}") from exc
    if parsed not in choices:
        raise ValueError(f"Invalid {field}")
    return parsed


def event_from_row(row: sqlite3.Row, day: date, source: str) -> dict:
    amount = money(row["amount"])
    kind = row["kind"]
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": kind,
        "amount": amount,
        "signed_amount": amount if kind == "income" else -amount,
        "date": day.isoformat(),
        "source": source,
        "status": row["status"] if source == "transaction" else "recurring",
        "note": row["note"],
    }


def parse_sheet_date(label: str, year: int) -> date | None:
    if not label:
        return None
    cleaned = label.replace("st", "").replace("nd", "").replace("rd", "").replace("th", "")
    try:
        return datetime.strptime(f"{cleaned} {year}", "%b %d %Y").date()
    except ValueError:
        return None


def parse_sheet_amount(value: str) -> float | None:
    cleaned = value.strip().replace("$", "").replace(",", "").replace("/", "")
    if not cleaned:
        return None
    try:
        parsed = money(cleaned)
        return parsed if parsed >= 0 else None
    except ValueError:
        return None


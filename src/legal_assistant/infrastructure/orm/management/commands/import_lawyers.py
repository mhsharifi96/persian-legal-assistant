from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from django.core.management.base import BaseCommand, CommandError

from legal_assistant.infrastructure.orm.repositories import OrmLawyerRepository
from legal_assistant.infrastructure.repositories.jsonl import lawyer_from_dict


class Command(BaseCommand):
    help = (
        "Import real lawyer profiles from a JSON or JSONL file into the database. "
        "Idempotent: rows are upserted on lawyer_id. This imports a REAL dataset "
        "you provide; it does not fabricate data."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("path", type=str, help="Path to a .json or .jsonl file")

    def handle(self, *args: Any, **options: Any) -> None:
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        repository = OrmLawyerRepository()
        count = 0
        for row in self._iter_records(path):
            repository.upsert_lawyer(lawyer_from_dict(row))
            count += 1
        self.stdout.write(
            self.style.SUCCESS(f"Imported/updated {count} lawyer(s) from {path}")
        )

    @staticmethod
    def _iter_records(path: Path) -> Iterator[dict[str, Any]]:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            data = json.loads(text)
            records = data if isinstance(data, list) else [data]
            yield from records
            return
        for line in text.splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)

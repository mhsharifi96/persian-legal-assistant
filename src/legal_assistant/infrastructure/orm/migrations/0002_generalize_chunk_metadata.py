from __future__ import annotations

from django.db import migrations


HIERARCHY_FIELDS = (
    "book",
    "bab",
    "fasl",
    "mabhas",
    "goftar",
    "article_number",
    "note_number",
)


def move_hierarchy_to_metadata(apps, schema_editor) -> None:
    LegalChunkRow = apps.get_model("legal_orm", "LegalChunkRow")
    for chunk in LegalChunkRow.objects.all().iterator():
        metadata = dict(chunk.metadata or {})
        hierarchy = dict(metadata.get("hierarchy") or {})
        for field in HIERARCHY_FIELDS:
            value = getattr(chunk, field)
            if value is not None:
                hierarchy[field] = value
                metadata.setdefault(field, value)
        metadata["hierarchy"] = hierarchy
        chunk.metadata = metadata
        chunk.save(update_fields=["metadata"])


class Migration(migrations.Migration):
    dependencies = [("legal_orm", "0001_initial")]

    operations = [
        migrations.RunPython(move_hierarchy_to_metadata, migrations.RunPython.noop),
        migrations.RemoveField(model_name="legalchunkrow", name="book"),
        migrations.RemoveField(model_name="legalchunkrow", name="bab"),
        migrations.RemoveField(model_name="legalchunkrow", name="fasl"),
        migrations.RemoveField(model_name="legalchunkrow", name="mabhas"),
        migrations.RemoveField(model_name="legalchunkrow", name="goftar"),
        migrations.RemoveField(model_name="legalchunkrow", name="article_number"),
        migrations.RemoveField(model_name="legalchunkrow", name="note_number"),
    ]

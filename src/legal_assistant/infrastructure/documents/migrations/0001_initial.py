from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="LegalFile",
            fields=[
                ("id", models.CharField(max_length=128, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=512)),
                ("file_url", models.URLField(blank=True, max_length=2048, null=True)),
                ("local_address_file", models.TextField(blank=True, null=True)),
                (
                    "ingestion_status",
                    models.CharField(
                        choices=[
                            ("pending", "در انتظار"),
                            ("indexed", "نمایه‌سازی شده"),
                            ("failed", "ناموفق"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("qdrant_points", models.PositiveIntegerField(default=0)),
                ("ingestion_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "فایل حقوقی",
                "verbose_name_plural": "فایل‌های حقوقی",
                "ordering": ("id",),
            },
        )
    ]

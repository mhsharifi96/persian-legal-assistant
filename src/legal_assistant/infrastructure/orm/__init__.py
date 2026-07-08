"""Django ORM persistence for the Persian Legal Assistant.

ORM models here are a persistence detail (infrastructure). Domain/application
code must not import them; adapters in ``repositories.py`` map ORM rows to and
from the frozen domain dataclasses.
"""

default_app_config = "legal_assistant.infrastructure.orm.apps.LegalOrmConfig"

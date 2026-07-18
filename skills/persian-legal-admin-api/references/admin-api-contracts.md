# Admin & API Contracts

Concrete contracts for the Django admin UI and DRF API. Read this before writing ORM models, adapters, serializers, or viewsets. The guiding constraint is `AGENT.md`'s dependency direction plus this skill's "real data, no fakes" rule.

## 1. ORM models are persistence, not domain

`domain/models.py` stays the single source of truth for business objects (`LawyerProfile`, `LegalDocument`, `LegalChunk`, `EvaluationRecord`, `Citation`, `RetrievedContext`). Django ORM models are a parallel persistence representation and must **not** be imported by `domain/` or `application/`.

Each ORM adapter maps both directions:

```python
# infrastructure/repositories/orm/lawyers.py
class OrmLawyerRepository:  # satisfies LawyerRepository (read) + LawyerWriteRepository
    def list_lawyers(self, *, filters: dict[str, Any] | None = None) -> list[LawyerProfile]:
        qs = LawyerRow.objects.all()
        qs = self._apply_filters(qs, filters)
        return [self._to_domain(row) for row in qs]

    def upsert_lawyer(self, lawyer: LawyerProfile) -> LawyerProfile:
        row, _ = LawyerRow.objects.update_or_create(
            external_id=lawyer.id, defaults=self._to_row_fields(lawyer)
        )
        return self._to_domain(row)

    @staticmethod
    def _to_domain(row: "LawyerRow") -> LawyerProfile: ...
    @staticmethod
    def _to_row_fields(lawyer: LawyerProfile) -> dict[str, Any]: ...
```

Mapping must be lossless for fields that services and citations depend on. For chunks, preserve every hierarchy field:
`document_id, source_uri, jurisdiction, law_title, document_type, book, bab, fasl, article_number, note_number, effective_date, publication_date, version, page_start, page_end, char_start, char_end, parser_name, chunking_strategy`.

## 2. Write ports (do not widen read ports)

The current ports are read-only (`LawyerRepository.list_lawyers`, `EvaluationRepository.load_records`). Admin/API writes need explicit, narrow write ports in `application/ports.py`:

```python
class LawyerWriteRepository(Protocol):
    def upsert_lawyer(self, lawyer: LawyerProfile) -> LawyerProfile: ...
    def delete_lawyer(self, lawyer_id: str) -> None: ...

class DocumentStore(Protocol):
    def save_document(self, document: LegalDocument, chunks: Sequence[LegalChunk]) -> None: ...
    def list_documents(self, *, filters: dict[str, Any] | None = None) -> list[LegalDocument]: ...

class EvaluationWriteRepository(Protocol):
    def append_record(self, record: EvaluationRecord) -> None: ...
```

Keep read and write ports separate so services that only read cannot accidentally mutate, and so tests can supply read-only fakes. One ORM class may implement several ports.

## 3. Bootstrap registry entries

Add ORM builders alongside the existing `fake`/`memory` ones and select by env — never edit service code to switch persistence:

```python
LAWYER_REPO_BUILDERS: dict[str, Callable[[Settings], LawyerRepository]] = {
    "fake": lambda s: InMemoryLawyerRepository(seed=[]),
    "jsonl": lambda s: JsonlLawyerRepository(s.lawyer_data_path),
    "orm": lambda s: OrmLawyerRepository(),
}

def build_lawyer_repository(settings: Settings) -> LawyerRepository:
    try:
        return LAWYER_REPO_BUILDERS[settings.lawyer_repo_provider](settings)
    except KeyError:
        raise ValueError(f"Unsupported lawyer repo provider: {settings.lawyer_repo_provider}")
```

Add the corresponding fields to `Settings`/`from_env` (e.g. `lawyer_repo_provider`, `document_store_provider`, `evaluation_repo_provider`) with env keys `LAWYER_REPO_PROVIDER`, etc.

## 4. Django settings ↔ typed Settings

`config/settings/base.py` is the Django settings module. It should build the app's typed `Settings` once and expose it for bootstrap, rather than re-reading env in two places:

```python
# config/settings/base.py
from legal_assistant.config.settings import Settings
LEGAL_ASSISTANT_SETTINGS = Settings.from_env()  # single source for provider selection
```

Django-only concerns (`INSTALLED_APPS`, `DATABASES`, `SECRET_KEY` from env, DRF config, auth) live in Django settings; provider/model selection stays in the typed `Settings`. `DATABASES['default']` comes from `DATABASE_URL`; default to Postgres for Docker, SQLite only for local scratch.

## 5. DRF viewset contracts

Business endpoints call services and serialize **domain DTOs**, keeping the API stable across persistence swaps:

```python
class LawyerRecommendationView(APIView):
    def post(self, request):
        query = RecommendRequestSerializer(data=request.data); query.is_valid(raise_exception=True)
        service: LawyerRecommendationService = request.app.lawyer_recommendation  # from bootstrap
        results = service.recommend(**query.validated_data)   # returns domain DTOs
        return Response(RecommendationSerializer(results, many=True).data)
```

Endpoint map (all under `/api/`):

| Method & path                 | Backed by                              | Notes |
|-------------------------------|----------------------------------------|-------|
| `GET/POST /lawyers`           | `LawyerRepository` / `LawyerWriteRepository` | CRUD; writes require auth |
| `POST /lawyers/recommend`     | `LawyerRecommendationService`          | scored results + Persian rationale |
| `GET /documents`, `/chunks`   | `DocumentStore`                        | hierarchy metadata read-only |
| `GET/POST /evaluations`       | `EvaluationRepository` / write port    | list/create records |
| `POST /evaluations/run`       | `EvaluationService`                    | RAGAS-style metrics |
| `POST /ask`                   | `build_agentic_graph(...)`             | Persian answer + `chunk_id` citations + insufficiency warning |

`POST /ask` needs a real `LLMPort` and retriever. In a production settings profile, if `LLM_PROVIDER=fake`, refuse with a clear typed error instead of returning a fake answer.

## 6. Django admin contracts

- Register `LawyerRow`, `LegalDocumentRow`, `LegalChunkRow`, `EvaluationRecordRow` with `ModelAdmin`.
- `list_display` / `list_filter` / `search_fields` on real legal fields: `law_title`, `jurisdiction`, `document_type`, `article_number`, `note_number`, lawyer specialty/location, evaluation metadata.
- Persian text: ensure UTF-8; do not normalize Persian/Arabic digits or characters for display (normalization is only for IDs/matching, per `AGENT.md`).
- Admin actions may call application services but must not reimplement recommendation/answer/evaluation logic.

## 7. "No fake data" seeding workflow

Real data enters only through:

1. **Migrations** — schema only; never data migrations that insert fabricated rows.
2. **Management commands** — `import_lawyers`, `import_legal_documents` read a real source file/dataset path (argument or env) provided by the user and write via the write ports/ingestion service. They must be idempotent (upsert on a stable external id).
3. **Admin / API** — human or client entry.

If the user has no dataset yet, deliver empty tables + working import commands + admin entry. An empty real store is correct; a fake-populated store is not. Test fixtures live under `tests/fixtures/` and never load in the app runtime.

## Acceptance recap

- ORM confined to infrastructure/interfaces; domain/application import zero Django/DRF/ORM.
- Read and write ports are distinct; services depend on the narrowest port they need.
- Persistence provider is env-selected through the bootstrap registry.
- Business endpoints go through services and serialize domain DTOs; only admin + CRUD touch ORM.
- Hierarchy metadata and Persian citations survive DB → service → serializer → JSON.
- No fabricated seed data; auth enforced on writes/admin; no hard-coded secrets or provider names.

# Neo4j node and relationship reference

This document describes the graph produced by the three current import paths:

- Dadrah consultations (`import_dadrah_to_neo4j.py`)
- Dadrah lawyer profiles (`import_lawyers_to_neo4j.py`)
- NovinLaw legislation and unanimity decisions (`import_novinlaw_to_neo4j.py`)

The examples below are representative values from the local source datasets. They are shortened for readability.

## Graph model at a glance

Every imported node has the base label `LegalEntity` and a globally unique `entity_id`.
The remaining labels identify its source and meaning:

```text
LegalEntity
├── DadrahNode
│   ├── Question ──TAGGED_WITH──> Tag
│   └── Question ──HAS_ANSWER───> Answer ──ANSWERED_BY──> Lawyer
└── LawNode
    ├── Laws: legislation hierarchy and citations
    └── Unanimity: unanimity-decision hierarchy and citations
```

Neo4j nodes can have several labels. For example, a NovinLaw statute document normally has
`LegalEntity`, `LawNode`, `Laws`, and `Law`. A statute referenced from the unanimity dataset may
also have `Unanimity`. Labels are additive; they are not separate copies of the node.

## Shared identity and properties

| Graph family | Identity | Shared labels | Main shared properties |
| --- | --- | --- | --- |
| Dadrah | `entity_id` | `LegalEntity`, `DadrahNode` | `type`, `name` |
| NovinLaw | `entity_id` (the crawler node ID) | `LegalEntity`, `LawNode`, plus `Laws` and/or `Unanimity` | `node_id`, `node_type`, `source_datasets`, `subtype`, `numeric_id`, `title`, `url`, `text`, `content_hash`, `fetched_at` |

For NovinLaw, `node_id` repeats `entity_id`. `source_datasets` is a list such as `["laws"]`,
`["unanimity"]`, or `["laws", "unanimity"]`. Additional properties are populated only when
the source provides them: `category`, `approval_info`, `year`, `decision_number`,
`approval_date`, `subject`, `issuing_body`, `access_status`, and `metadata_json`.

## Dadrah nodes

All four types below also have the labels `LegalEntity` and `DadrahNode`.

### `Question`

Represents one public consultation question.

| Property | Meaning | Example |
| --- | --- | --- |
| `entity_id` | Stable ID derived from the request ID | `question:864359` |
| `type`, `name` | Type discriminator and display name | `Question`, `مشاوره حقوقی رایگان - بیمه فرزند خواندگی` |
| `request_id` | Dadrah consultation ID | `864359` |
| `title`, `text` | Question title and body | `... بیمه فرزند خواندگی`, `من دختر به فرزندی گرفتم ...` |
| `page_url` | Original consultation page | `https://www.dadrah.ir/consulting-paper.php?requestID=864359` |
| `fetched_at` | Crawl timestamp | `2026-07-17T21:06:58...+00:00` |
| `source_file`, `source_line` | JSONL provenance | `chunk_08_864274_873455.jsonl`, line number |
| `trust_tier` | Content-quality classification | `public_user_generated_consultation` |

Outgoing relationships:

- `(:Question)-[:TAGGED_WITH]->(:Tag)` for each topic tag.
- `(:Question)-[:HAS_ANSWER]->(:Answer)` for each response.

### `Answer`

Represents one answer to a consultation. It is deliberately a separate node because a question
can have many ordered responses.

| Property | Meaning | Example |
| --- | --- | --- |
| `entity_id` | Request ID plus one-based answer position | `answer:864359:1` |
| `type`, `name` | Type and display label | `Answer`, `پاسخ 1` |
| `request_id` | Parent consultation ID | `864359` |
| `position`, `answer_number` | Answer order and source number | `1`, `1` |
| `text` | Answer body | `باید از سازمان تامین اجتماعی تماس بگیرید ...` |
| `date`, `time` | Source publication date and time | `۱۴۰۵/۲/۵`, `۱۲:۵۵:۲۰` |

Incoming/outgoing relationships:

- `(:Question)-[:HAS_ANSWER]->(:Answer)` identifies the answered question.
- `(:Answer)-[:ANSWERED_BY]->(:Lawyer)` identifies the author. Despite the relationship name,
  its direction is from the answer to the lawyer.

### `Tag`

Represents a normalized topic shared by any number of questions.

| Property | Meaning | Example |
| --- | --- | --- |
| `entity_id` | SHA-1-based stable ID of the normalized tag name | `tag:<20-hex-digest>` |
| `type`, `name` | Type and original topic name | `Tag`, `بیمه تامین اجتماعی` |
| `url` | Dadrah tag page, when present | `https://www.dadrah.ir/tag.php?tag=بیمه تامین اجتماعی` |

Incoming relationship: `(:Question)-[:TAGGED_WITH]->(:Tag)`.

### `Lawyer`

Represents a lawyer who authored an answer and/or was imported from the full lawyer-profile
dataset. Profile import enriches the same node when its stable URL-based identity matches.

| Property | Meaning | Example |
| --- | --- | --- |
| `entity_id` | SHA-1-based stable ID of slug URL, profile URL, or name | `lawyer:<20-hex-digest>` |
| `type`, `name` | Type and lawyer name | `Lawyer`, `مجید کریمی زاده` |
| `city`, `profile_url` | Location and public profile | `""` (not supplied), `https://www.dadrah.ir/...` |
| `lawyer_id` | Dadrah numeric lawyer ID (profile import) | `30` |
| `listing_name`, `slug_url` | Listing title and canonical short URL | `... وکیل پایه یک`, `https://www.dadrah.ir/5f1e6f0bb2e6b` |
| `email`, `address` | Public profile contact fields | `mj...@yahoo.com`, `اهواز میدان امانیه` |
| `specialties` | List of profile specialty descriptions | `["دعاوی مالی، تجاری، قراردادها ..."]` |
| `source` | Profile source | `dadrah.ir` |
| `source_status`, `source_updated_at` | Profile-crawl state and timestamp | `done`, `2026-07-18T23:37:36...+00:00` |

Incoming relationship: `(:Answer)-[:ANSWERED_BY]->(:Lawyer)`.

## NovinLaw legislation nodes (`Laws`)

Every node in this section has `LegalEntity`, `LawNode`, and `Laws`. The type-specific labels
are assigned as follows.

| Crawler type | Neo4j semantic label(s) | Purpose | Representative example | Direct structural relationships |
| --- | --- | --- | --- | --- |
| `index` | `Index` | Root legislation listing | `index:lists`, `قوانین و مقررات` | `LINKS_TO` categories/documents |
| `category` | `LegalCategory` | Top-level subject, such as civil or economic law | `category:1`, `حقوقی` | `CONTAINS` law groups/documents; `LINKS_TO` navigational targets |
| `law_group` | `Law`, `LawGroup` | A law split into multiple child documents | `law_group:1`, `قانون مدنی` | `CONTAINS` documents; `LINKS_TO` navigation |
| `document` | `Law` | A crawled statute or a section of a grouped statute | `document:child:10`, `شرکت نسبی (183-189)` | `CONTAINS` articles; may cite other legal nodes |
| `article` | `Article` | One `ماده` or constitutional `اصل` extracted from a document | `article:document:child:100:ماده:24`, `ماده 24` | `CONTAINS` notes; may cite other legal nodes |
| `note` | `Note` | One `تبصره` extracted from an article | `note:article:document:child:100:ماده:24:1`, `تبصره 1` | May cite other legal nodes |
| `unresolved_reference` | `UnresolvedLegalReference` | A citation whose target could not be resolved confidently | `unresolved:002d...`, `ماده ۲ قانون کیفیت اخذ پروانه ...` | Incoming citation relationship |

Important type details:

- An `Article` uses `subtype` to preserve `ماده` versus `اصل`, and `numeric_id` for its number.
- A `Note` uses `subtype = "تبصره"` and a `numeric_id` generated from the printed number or its order.
- A `Law` document may contain `category`, `approval_info`, full `text`, and `content_hash`.
- `LawGroup` intentionally also receives the broader `Law` label, so `MATCH (n:Law)` returns
  both grouped laws and concrete documents.

### Legislation relationships

| Relationship | Meaning | Typical pattern |
| --- | --- | --- |
| `CONTAINS` | Legal/structural parenthood | `LegalCategory -> LawGroup -> Law -> Article -> Note` (some categories directly contain documents) |
| `LINKS_TO` | A navigational hyperlink discovered by the crawler; not necessarily legal semantics | `Law -> LawGroup`, `LegalCategory -> Index` |
| `REFERENCES` | Neutral citation | `Article -> Article/Law/LawGroup/UnresolvedLegalReference` |
| `AMENDS` | Source text amends or adds to the target | `Article -> Article` |
| `REPEALS` | Source text repeals the target | `Law/Article/Note -> legal target` |
| `IMPLEMENTS` | Source text implements or executes the target | `Law/Article/Note -> legal target` |

Citation targets can be `Article`, `Law`, `LawGroup`, or `UnresolvedLegalReference`. Citation
sources are normally `Law`, `Article`, or `Note`.

## NovinLaw unanimity nodes (`Unanimity`)

Every node in this section has `LegalEntity`, `LawNode`, and `Unanimity`.

| Crawler type | Neo4j semantic label(s) | Purpose | Representative example |
| --- | --- | --- | --- |
| `index` | `Index` | Root list of unanimity decisions | `unanimity:index`, `آراء وحدت رویه` |
| `year` | `DecisionYear` | Groups decisions by Persian calendar year | `unanimity_year:1`, `آراء وحدت رویه سال 1323` |
| `decision` | `LegalDecision`, `UnanimityDecision` | Full unanimity decision | `unanimity_decision:1`, `رأی وحدت رویه شماره 224` |
| `institution` | `Organization` | Issuing judicial body | `institution:011a...`, `هیأت عمومی دیوان عالی کشور` |
| `legal_document` | `Law` | A cited law resolved against the legislation database | `document:child:504`, `فرار محبوسین قانونی ...` |
| `legal_provision` | `LegalProvision` | A cited article resolved against the legislation database | `article:document:child:775:ماده:31`, `ماده 31` |
| `external_legal_document` | `ExternalLegalDocument` | A cited law title not resolved to the legislation database | `external_legal_document:0027...`, a captured law title |
| `external_legal_provision` | `ExternalLegalProvision` | A cited provision without a resolved internal provision | `external_legal_provision:00e9...`, `ماده 160 از ...` |
| `unresolved_legal_reference` | `UnresolvedLegalReference` | A citation too incomplete to identify a document | `unresolved_legal_reference:03bb...`, `مواد ۱۸، ۴۰` |
| `external_unanimity_decision` | `ExternalUnanimityDecision` | A cited decision not present or not uniquely matched locally | `external_unanimity_decision:41cf...`, `رأی وحدت رویه شماره 52` |

`UnanimityDecision` additionally uses `year`, `decision_number`, `approval_date`, `subject`,
`issuing_body`, `text`, and `access_status`. Reference-only nodes normally have
`access_status = "reference_only"`; resolved statute references use
`access_status = "linked_from_legal_db"`.

### Unanimity relationships

| Relationship | Meaning | Typical pattern |
| --- | --- | --- |
| `CONTAINS` | Hierarchy or document/provision membership | `DecisionYear -> UnanimityDecision`; `Law/ExternalLegalDocument -> LegalProvision/ExternalLegalProvision` |
| `LISTS` | Root index lists a decision | `Index -> UnanimityDecision` |
| `ISSUED_BY` | Judicial body that issued a decision | `UnanimityDecision -> Organization` |
| `LINKS_TO` | Raw navigation link | `Index/DecisionYear/UnanimityDecision -> navigational node` |
| `ADJACENT_DECISION` | Crawler-discovered neighboring decision | `UnanimityDecision -> UnanimityDecision` |
| `NEXT_DECISION` | Chronologically/numerically finalized next decision | `UnanimityDecision -> UnanimityDecision` |
| `PREVIOUS_DECISION` | Finalized previous decision | `UnanimityDecision -> UnanimityDecision` |
| `REFERENCES` | Neutral statute/provision citation | `UnanimityDecision -> legal target` |
| `APPLIES` | Decision applies or relies on the target | `UnanimityDecision -> legal target` |
| `IMPLEMENTS` | Decision implements the target | `UnanimityDecision -> legal target` |
| `INTERPRETS_AMENDMENT` | Decision interprets an amendment/addition/change | `UnanimityDecision -> legal target` |
| `REPEALS_OR_DISAPPLIES` | Decision treats the target as repealed or inapplicable | `UnanimityDecision -> legal target` |
| `CITES_DECISION` | Neutral citation to another unanimity decision | `UnanimityDecision -> UnanimityDecision/ExternalUnanimityDecision` |
| `OVERRULES_DECISION` | Later decision overrules an earlier decision when that wording is detected | `UnanimityDecision -> UnanimityDecision/ExternalUnanimityDecision` |
| `AFFIRMS_DECISION` | Decision affirms another decision | `UnanimityDecision -> UnanimityDecision/ExternalUnanimityDecision` |
| `DISTINGUISHES_DECISION` | Decision distinguishes or conflicts with another decision | `UnanimityDecision -> UnanimityDecision/ExternalUnanimityDecision` |

The final three decision-to-decision types are supported by the crawler/importer even if a
particular dataset snapshot contains no matching edge.

## NovinLaw relationship properties

Unlike Dadrah relationships, every imported NovinLaw relationship carries provenance:

| Property | Meaning |
| --- | --- |
| `relation_key` | SHA-256 of source ID, target ID, type, and raw reference; permits multiple distinct citations between the same two nodes |
| `source_datasets` | Dataset(s) that supplied the relationship |
| `raw_reference` | Exact citation phrase captured from the Persian text, or an empty string for structural links |
| `confidence` | Crawler confidence from `0.0` to `1.0` |
| `source_url` | Page on which the relationship was discovered |

## Cross-dataset merging

The legislation and unanimity importers merge on the same `entity_id`. This is intentional.
For example, if a decision resolves a citation to `article:document:child:775:ماده:31`, the
existing legislation `Article` node is reused and gains `LegalProvision` and `Unanimity` labels.
Similarly, a resolved document can have both `Laws` and `Unanimity` plus the shared `Law` label.
No duplicate citation-only copy is created.

The `node_type` property favors the legislation type when the node came from both datasets.
Use labels and `source_datasets`, rather than `node_type` alone, to understand these merged nodes.

## Example Cypher queries

Find one consultation, its answers, and their lawyers:

```cypher
MATCH (q:Question {request_id: '864359'})-[:HAS_ANSWER]->(a:Answer)
OPTIONAL MATCH (a)-[:ANSWERED_BY]->(lawyer:Lawyer)
RETURN q.title, a.position, a.text, lawyer.name
ORDER BY a.position;
```

Traverse a law down to its provisions:

```cypher
MATCH path=(law:Law {entity_id: 'law_group:1'})-[:CONTAINS*1..3]->(part)
RETURN path;
```

Find legal authorities used by a unanimity decision:

```cypher
MATCH (decision:UnanimityDecision {decision_number: '224'})-[r]->(authority)
WHERE type(r) IN [
  'REFERENCES', 'APPLIES', 'IMPLEMENTS',
  'INTERPRETS_AMENDMENT', 'REPEALS_OR_DISAPPLIES'
]
RETURN type(r), authority.entity_id, authority.title,
       r.raw_reference, r.confidence
ORDER BY r.confidence DESC;
```

Inspect the complete labels of nodes shared by both NovinLaw datasets:

```cypher
MATCH (node:LawNode)
WHERE 'laws' IN node.source_datasets AND 'unanimity' IN node.source_datasets
RETURN node.entity_id, labels(node), node.title
LIMIT 50;
```

## Constraints and indexes

The importers create these schema protections:

- Unique `LegalEntity.entity_id` across all graph families.
- Unique `DadrahNode.entity_id` and `Lawyer.lawyer_id`.
- Unique `LawNode.entity_id`.
- Indexes for `Question.request_id`, `Answer.request_id`, `LawNode.node_type`, and
  `UnanimityDecision.decision_number`.

All imports use Cypher `MERGE`, so rerunning an importer updates/enriches existing nodes and
relationships instead of duplicating them.

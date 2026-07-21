"""Read-only retrieval adapters for the legal research agent."""

from legal_assistant.infrastructure.retrieval.neo4j import Neo4jLegalGraphSearch
from legal_assistant.infrastructure.retrieval.qdrant import QdrantLegalVectorSearch

__all__ = ["Neo4jLegalGraphSearch", "QdrantLegalVectorSearch"]

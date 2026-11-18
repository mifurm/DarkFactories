"""Cosmos DB container catalogue. MUST match infra/resources.bicep `cosmosContainers` (enforced by a unit test).

Partition-key strategy (all containers use the `/pk` path):
  * "id"    - high-cardinality transactional documents: pk = document id (point reads, even spread)
  * "const" - small reference / analytics collections: pk = collection name (single logical partition; cross-document
              reads stay single-partition. Scale-out path for analytics = Fabric / ADX, see ARCHITECTURE.md)
"""

from __future__ import annotations

COLLECTIONS: dict[str, str] = {
    "conversations": "id",
    "audit": "id",
    "access_audit": "id",
    "approvals": "id",
    "idempotency": "id",
    "payments": "id",
    "bo_customers": "const",
    "bo_orders": "const",
    "bo_shipments": "const",
    "bo_appointments": "const",
    "bo_returns": "id",
    "bo_refunds": "id",
    "bo_credits": "id",
    "bo_tickets": "id",
    "bo_warranty": "id",
    "kb_docs": "const",
    "kb_chunks": "const",
    "kb_versions": "const",
    "history": "const",
    "wfm_history": "const",
    "voc": "const",
    "qa_reviews": "id",
    "eval_runs": "id",
    "agent_configs": "const",
    "rollouts": "const",
    "campaigns": "const",
    "callbacks": "id",
    "contact_prefs": "const",
    "usage_daily": "id",
    "seed_meta": "const",
    "embeddings_cache": "const",
    "settings": "const",
    "telephony_calls": "id",
    "metrics_samples": "id",
}

BACKOFFICE_COLLECTIONS = [
    "bo_customers",
    "bo_orders",
    "bo_shipments",
    "bo_appointments",
    "bo_returns",
    "bo_refunds",
    "bo_credits",
    "bo_tickets",
    "bo_warranty",
]


def partition_key(coll: str, doc_id: str) -> str:
    mode = COLLECTIONS.get(coll)
    if mode is None:
        raise KeyError(f"unknown collection '{coll}'")
    return doc_id if mode == "id" else coll

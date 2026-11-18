"""Wires engine singletons onto the Services container."""

from __future__ import annotations

from typing import Any

from .backoffice import BackOffice
from .crm import ConnectorBackOffice, MockCrmConnector
from .kb import KnowledgeBase
from .orchestrator import Orchestrator
from .routing import default_workers
from .store import ConfigStore, ConversationStore
from .tools import ToolExecutor


def attach_engine(svc: Any, shared_kb: Any = None, shared_configs: Any = None) -> None:
    """Attach back-office, KB, conversation store, config store, tool executor and orchestrator (sandbox reuses KB + configs)."""
    svc.backoffice = BackOffice(svc.repo)
    svc.kb = shared_kb or KnowledgeBase(svc.repo, svc.llm, svc.audit, svc.guard)
    svc.store = ConversationStore(svc.repo, svc.bus)
    svc.configs = ConfigStore(svc.repo, svc.audit)
    if shared_configs is not None:
        svc.configs._cache = dict(shared_configs._cache)
        svc.configs.active_id = shared_configs.active_id
    svc.tools = ToolExecutor()
    svc.orchestrator = Orchestrator(svc)
    svc.ext["crm"] = MockCrmConnector(svc.backoffice)
    svc.oms = ConnectorBackOffice(svc.backoffice, svc.ext["crm"])
    svc.ext.setdefault("workers", default_workers())
    if svc.llm.deterministic and hasattr(svc.llm, "brain") and svc.llm.brain is None:
        from .stub_brain import brain

        svc.llm.brain = brain

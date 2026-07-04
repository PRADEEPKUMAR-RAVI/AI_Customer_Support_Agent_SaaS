"""M3 knowledge domain — pure, I/O-free logic (chunking, source FSM helpers).

Everything here is deterministic and dependency-light so it runs under ``make test`` with no
database or vendor keys. The RAG orchestration that uses it lives in
``app/services/knowledge_service.py``.
"""

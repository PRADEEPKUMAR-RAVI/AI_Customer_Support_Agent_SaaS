"""Celery task modules. Tasks are thin wrappers that drive async service code via
``asyncio.run`` and open their own ``with_tenant`` session (workers have no request scope).
Module-name prefixes map to queues in ``app/infra/queue/celery_app.py`` (``ingestion`` -> batch).
"""

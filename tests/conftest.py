"""Test config. Pure-logic tests run anywhere (no services). Tests marked ``rls`` need a live
Postgres with the migration applied and are skipped unless ``RUN_RLS_TESTS=1``."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_RLS_TESTS") == "1":
        return
    skip_rls = pytest.mark.skip(reason="set RUN_RLS_TESTS=1 with a live Postgres to run")
    for item in items:
        if "rls" in item.keywords:
            item.add_marker(skip_rls)

"""Seed data for one-shot bootstrap endpoints.

These modules expose plain-Python payload lists that mirror what the FE would
otherwise POST. They are the source of truth for the
``POST /api/v3/sla-masters/seed-defaults`` endpoint and (going forward) for
the smoke tests under ``tests/`` that today inline-define the same data.
"""
from app.seed_data.sla_master_seeds import ALL_SEED_SLAS, SEEDS_BY_CONTRACT

__all__ = ["ALL_SEED_SLAS", "SEEDS_BY_CONTRACT"]

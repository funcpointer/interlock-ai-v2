"""LLM-augmented pipeline (Track 2) for v2 hybrid architecture.

Track 1 (deterministic regex + heuristic alignment) stays frozen under
`src/interlock/{align,extract,detect}`. This package adds the
foundation-model layer for document classification (Sprint 1), LLM
extraction (Sprint 2), pairing reranker (Sprint 4), standards-as-RAG
(Sprint 5), and coupled-effect graph traversal (Sprint 5).

See `docs/PIVOT_PLAN.md` for the architecture; per-sprint specs live
in `docs/superpowers/specs/`.
"""

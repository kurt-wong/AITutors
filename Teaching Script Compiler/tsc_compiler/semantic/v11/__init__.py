"""Semantic Retrieval V1.1 candidate (isolated).

This package is a *candidate* path. It never changes the V1 default model,
thresholds, index or decision path. The only shared code is the unmodified
``tsc_compiler.semantic.retrieval.SemanticIndex`` decision engine, instantiated
with an independent document set, embedding matrix and frozen V1.1 config.
"""

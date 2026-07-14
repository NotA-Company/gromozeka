#!/usr/bin/env ./venv/bin/python3
"""Test-generate embeddings for a given fastembed TextEmbedding model.

Loads the requested model via ``fastembed.TextEmbedding``, prints its embedding
dimension, then generates and prints diagnostics (first 5 vector values, dtype,
byte size) for each sample text. Useful for verifying a model downloads and
serves correctly before wiring it into the memory-embedding subsystem.

Usage::

    ./venv/bin/python3 scripts/fastembed_test_model.py <modelName>

Example::

    ./venv/bin/python3 scripts/fastembed_test_model.py \
        sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
"""

from __future__ import annotations

import argparse
import sys

from fastembed import TextEmbedding

# Sample texts used to verify the model produces embeddings end-to-end.
_SAMPLE_TEXTS: list[str] = [
    "Hello, how are you?",
    "Where are you right now?",
    "Send me the link to that document.",
    "I didn't understand what you meant.",
]


def testFastembedModel(modelName: str) -> None:
    """Load a fastembed model and print embedding diagnostics for sample texts.

    Args:
        modelName: The HuggingFace model name (e.g.
            ``sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2``).
    """
    print(f"Loading model: {modelName} ...")
    model = TextEmbedding(model_name=modelName, quantize=False)

    print(f"Embedding dimension: {model.embedding_size}")
    print("Generating embeddings:\n")

    for text in _SAMPLE_TEXTS:
        embedding = list(model.embed([text]))[0]
        print(f"Text: {text}")
        print(f"Vector (first 5 values): {embedding[:5]}")
        print(f"dtype: {embedding.dtype}, size: {embedding.nbytes} bytes\n")


def main() -> int:
    """Entry point: parse CLI args and test the requested model.

    Returns:
        ``0`` on success.
    """
    parser = argparse.ArgumentParser(
        description="Test-generate embeddings for a given fastembed TextEmbedding model.",
    )
    parser.add_argument(
        "modelName",
        type=str,
        help=("HuggingFace model name, e.g. " "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2."),
    )
    args = parser.parse_args()
    testFastembedModel(args.modelName)
    return 0


if __name__ == "__main__":
    sys.exit(main())

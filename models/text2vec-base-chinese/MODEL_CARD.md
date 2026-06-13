# Model Card

## Model Details

- Name: `text2vec-base-chinese`
- Format: SentenceTransformers-compatible local directory
- Base architecture: BERT/MacBERT-style encoder
- Output: 768-dimensional sentence embedding
- Pooling: mean token pooling
- Maximum configured sequence length: 128 tokens

## Intended Use

This model is intended for Chinese semantic retrieval, text similarity,
clustering, and vector indexing workflows. It can be used as one component in a
RAG or recommendation pipeline.

## Out-of-Scope Use

- Making final safety, legal, medical, or financial decisions.
- Treating vector similarity as proof of factual correctness.
- Processing long documents without chunking.
- Processing private or regulated data without application-level controls.

## Source and License

The local configuration references `hfl/chinese-macbert-base`. Complete source,
license, and redistribution review before commercial release. This file records
the required review item but does not itself grant any license.

## Evaluation Requirements

Before production use, run a domain-specific retrieval evaluation set covering:

- Short and long Chinese text.
- Mixed Chinese/English text.
- Near-duplicate scenes or plot summaries.
- Negative pairs with shared keywords but different meaning.
- Long-context cases that require chunking.


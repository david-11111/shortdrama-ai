# text2vec-base-chinese

This directory contains an offline Chinese sentence embedding model in
SentenceTransformers format. It is intended for semantic retrieval, text
similarity, clustering, reranking prefilters, and RAG vector indexing.

## Model Purpose

The model uses a BERT/MacBERT encoder and mean pooling to convert text into a
768-dimensional sentence vector.

Important files:

- `config.json`: BERT encoder configuration.
- `model.safetensors`: model weights.
- `vocab.txt`: tokenizer vocabulary.
- `tokenizer_config.json`: tokenizer behavior.
- `sentence_bert_config.json`: SentenceTransformers runtime settings.
- `1_Pooling/config.json`: sentence embedding pooling settings.

## Runtime Limits

The effective SentenceTransformers sequence limit is:

```json
{
  "max_seq_length": 128
}
```

Inputs longer than this are normally truncated by the embedding pipeline. This
does not crash the model, but it can silently drop important context.

For long scripts, plot summaries, conversations, or documents:

1. Split text into stable chunks before embedding.
2. Prefer overlap between adjacent chunks when context continuity matters.
3. Store chunk ids and source offsets with the vectors.
4. Aggregate or rerank retrieved chunks at the application layer.

Do not pass entire long documents directly to this model and assume the full
context was embedded.

## Tokenizer Case Handling

`tokenizer_config.json` and `sentence_bert_config.json` are aligned to
`do_lower_case: true`. This keeps SentenceTransformers loading behavior
consistent with the local tokenizer configuration.

For mostly Chinese text this has little effect. For mixed Chinese/English text,
uppercase English tokens are normalized to lowercase during tokenization.

## Expected Shapes

The local assets should satisfy these checks:

- Vocabulary size: `21128`
- Word embedding weight: `(21128, 768)`
- Position embedding weight: `(512, 768)`
- Token type embedding weight: `(2, 768)`
- Pooling dimension: `768`

Run the local integrity check after copying, replacing, or upgrading model
files:

```bash
python validate_model_assets.py
```

## Operational Notes

- Load the model once per service process and reuse it across requests.
- Batch small embedding requests where practical, but cap batch size according
  to available memory.
- Keep user-facing chunking limits in application code, not by editing this
  model directory.
- Do not edit `model.safetensors` manually.


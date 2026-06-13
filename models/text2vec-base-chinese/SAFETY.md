# Safety Notes

This model directory contains an embedding model, not a generative model. It
does not produce free-form text, execute tools, or make autonomous decisions.
The main risks are retrieval quality, privacy handling, supply-chain integrity,
and misuse in downstream ranking or recommendation systems.

## Known Limits

- Inputs longer than `max_seq_length` are truncated by the embedding pipeline.
- Embeddings may underrepresent late context in long scripts or documents.
- The model may encode social, cultural, or language distribution biases from
  its training data.
- Similarity scores are not factuality, safety, or copyright judgments.
- The model does not detect private data by itself.

## Required Application Controls

- Chunk long documents before embedding and keep source offsets.
- Do not use vector similarity as the only safety or moderation signal.
- Avoid embedding unnecessary secrets, credentials, or regulated personal data.
- Add access control around vector indexes, because embeddings can leak
  information about source text.
- Log model version and asset manifest hash for each deployment.

## Release Gate

Before commercial release, complete:

- Source and license review.
- Data retention and privacy review for embedded content.
- Abuse-case review for retrieval and recommendation use cases.
- Regression set for retrieval quality on real product traffic.
- Monitoring for unexpected recall failures and high-risk queries.



# Plan for Vectorize-based Embeddings with Similarity Ranking

## Goals

- Implement a vectorization workflow using OpenAI's text-embedding-3-small.
- Persist embeddings in the database (embedding_vec).
- Expose a vectorization entrypoint: uv main.py vectorize.
- Rank search results by cosine similarity using a dedicated ISimilaritySearch interface.
- Keep the UI unchanged; use existing pagination.
- Ensure the vectorize process is interruptible and resumable.

## Components

### 1. Database

- Extend jobs_data with a new column embedding_vec (TEXT) to store JSON-encoded embedding vectors.
- Backward compatibility: if missing, embeddings will be generated during vectorize.

### 2. Embedding Layer (new module)

- File: vectorizor.py
- Interfaces:
    - IVectorizer with method embed(content: str) -> List[float]
    - OpenAIEmbeddingVectorizer implementing IVectorizer using OpenAI's text-embedding-3-small
    - get_vectorizer() -> IVectorizer factory
- Behavior:
    - Vectorize listings’ descriptions during uv main.py vectorize.
    - Persist embeddings to embedding_vec as JSON arrays.
    - Support resume via a checkpoint file (e.g., vectorize.chk).

### 3. Similarity Layer (new module)

- File: similarity.py
- Interfaces:
    - ISimilaritySearch with method score(a: List[float], b: List[float]) -> float
- Implementations:
    - CosineSimilaritySearch using cosine similarity
    - Optional: get_similarity_search() factory
- Integration:
    - App search path uses this interface to rank results.

### 4. CLI and Vectorization Orchestration

- File: main.py
- Command: vectorize
    - uv main.py vectorize [--resume] [--top-n N]
    - Vectorizes all or batches of listings’ descriptions, storing embeddings
    - Resume support via vectorize.chk
    - Silent run (no stdout output)

### 5. Web App

- File: app.py
- Search flow:
    - Load listings and their embedding_vec
    - Vectorize the query string (same model) to query_vec
    - Compute similarity via ISimilaritySearch.score(query_vec, listing_vec) for each listing
    - Sort by score descending
    - Paginate to match the existing main page behavior
- No UI template changes

### 6. Interactions and Guarantees

- No changes to the scraper; vectorization is decoupled.
- Output remains a UI-driven experience; vectorization enhances search quality.
- If OpenAI API key is missing or unavailable, vectorize will raise a clear error.
- Per-page pagination matches existing behavior (default 10 per page unless configured elsewhere).

### 7. Error Handling and Validation

- Robust parsing/serialization of embedding vectors (JSON arrays).
- Graceful skipping of listings with missing embeddings during search.
- Clear error messages if the embedding API cannot be reached.

### 8. Testing and Validation

- Unit tests (where applicable) for:
    - Cosine similarity scoring
    - Embedding serialization/deserialization
- Manual validation steps:
    - Run uv main.py vectorize --resume
    - Start app and perform a search like "freelance"
    - Verify results are ranked by similarity and paginated

### 9. Milestones

1. Add vectorizor.py with IVectorizer and OpenAIEmbeddingVectorizer; implement get_vectorizer().
2. Add similarity.py with ISimilaritySearch and CosineSimilaritySearch.
3. Update app.py to use ISimilaritySearch for ranking.
4. Update main.py to implement vectorize entrypoint and checkpointing.
5. Extend DB schema to add embedding_vec.
6. Implement tests/validation plan and runbook.

### 10. Next Steps

- Await confirmation to proceed with patch generation and application.
- If you want any adjustments (e.g., a different similarity metric, or a different checkpoint format), specify before I patch.

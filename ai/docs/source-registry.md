# Source registry design

The registry separates a scientific work from the exact file indexed by RAG. A catalog record identifies the publication; an artifact is a particular downloaded PDF, identified by SHA-256. A later download with different bytes is a new artifact, even when the catalog URL stays the same.

## Source record

Store `source_id`, provider and provider ID, title, authors, publisher, publication date, catalog URL, document URL, experiment, report numbers, optional DOI, optional declared document version, and catalog validation status. Missing DOI or version stays `NULL`; neither is inferred from a dataset DOI. Catalog verification means that a human checked the record against the publisher's page. It does not mean that the PDF text has been reviewed.

The first curated record is [NASA NTRS 20130014061](https://ntrs.nasa.gov/citations/20130014061), a FLEX paper. NASA lists its authors, publication date, report numbers and public distribution. NTRS does not show a DOI or document version for this record, so both are null in the manifest.

## Artifact and chunk records

An artifact stores `source_id`, SHA-256 of raw bytes, retrieval time, MIME type, page count, extraction tool/version, and status (`downloaded`, `extracted`, `reviewed`, `rejected`). The SHA-256 is unique per source. Every chunk stores an artifact ID, 1-based page start/end, section label when detected, position within the page, exact extracted text, text hash, embedding model and dimensions. Text and embeddings are reindexed if the artifact hash, extraction algorithm or embedding model changes. A rejected artifact cannot be searched.

The database implementation belongs in the private `ai` schema. `scientific` owns measurements and trial provenance; the registry can reference PSI IDs but cannot duplicate Stanley's values. `app` owns operational user data. The server-side AI role should have only the needed access. No public Data API grants are required for the registry.

## Validation and citations

Catalog validation, artifact review and claim validation are distinct. Retrieval must return only reviewed artifacts. A citation carries `source_id`, artifact hash, page range, optional section, and catalog URL. Before presenting an answer, validate that every cited chunk exists in the retrieved set and its quoted evidence occurs in that chunk. A citation to a document alone is insufficient for a scientific claim. Numerical answers from `scientific` need dataset, trial/row and unit provenance from Stanley's query contract.

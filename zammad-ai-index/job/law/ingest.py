"""Law ingestion helpers.

This module implements a minimal, configuration-driven pipeline to fetch a law
document from a given URL, extract paragraphs, chunk content, and index chunks
into Qdrant with typed metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone
from logging import Logger
from urllib.request import Request, urlopen
from uuid import NAMESPACE_DNS, UUID, uuid5

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from markdownify import markdownify as md
from pydantic import BaseModel, Field, PositiveInt

from job.qdrant.qdrant import QdrantKBClient
from job.settings.law import LawConfig
from job.utils.hash import hash_content, normalize_content
from job.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai-index.law")


def _fetch_html(url: str, timeout: PositiveInt = 60) -> str:
    """Fetch raw HTML from a URL using a simple urllib Request.

    Keep implementation minimal to avoid new dependencies.
    """
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (urllib is acceptable here)
        return resp.read().decode("utf-8", errors="ignore")


class Paragraph(BaseModel):
    """Typed paragraph extracted from markdown.

    Keep fields small: full text and any references. Also preserve paragraph
    identifier and title for metadata convenience.
    """
    paragraph: str
    title: str = ""
    full: str
    references: list[str] = Field(default_factory=list)


def _extract_paragraphs_from_markdown(markdown_text: str) -> list[Paragraph]:
    """Extract paragraphs based on markdownify-produced '### § <num><title>' headings.

    Returns list of Paragraph model instances.
    """
    import re

    # Heading pattern emitted by markdownify for <h3> elements
    # Example: '### § 11 Eignung zum Führen ...\n'
    para_re = re.compile(r"^### § (?P<num>\d+[a-z]?)(?P<title>.*)$", re.MULTILINE)

    matches = list(para_re.finditer(markdown_text))
    if not matches:
        logger.warning("No paragraph headings detected in markdown text")

    paragraphs: list[Paragraph] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown_text)
        para_num = m.group("num").strip()
        para_title = (m.group("title") or "").strip()
        body = markdown_text[start:end].strip()
        full = f"§ {para_num} {para_title}\n\n{body}".strip()
        paragraphs.append(Paragraph(paragraph=para_num, title=para_title, full=full))
    return paragraphs


class Annex(BaseModel):
    """Typed annex extracted from markdown.

    Contains the full annex text and the list of references it mentions.
    """
    annex: str
    title: str = ""
    full: str
    references: list[str] = Field(default_factory=list)


def _extract_annexes_from_markdown(markdown_text: str) -> list[Annex]:
    """Extract annexes based on markdownify-produced '### Anlage <num><title>' headings.

    Returns list of Annex model instances.
    """
    import re

    # Handle annex headings like "### Anlage 4 (zu $ 15a) Fahrerlaubsnisanhang"
    annex_re = re.compile(r"### Anlage (?P<num>\d+[a-z]?).+\(zu (?P<references>.+?)\) (?P<title>.+)\n", re.MULTILINE)

    matches = list(annex_re.finditer(markdown_text))
    if not matches:
        logger.debug("No annex headings detected in markdown text")

    annexes: list[Annex] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown_text)
        annex_num = m.group("num").strip()
        annex_title = (m.group("title") or "").strip()
        annex_references = [ref.strip() for ref in m.group("references").split(",")]
        body = markdown_text[start:end].strip()
        full = f"Anlage {annex_num} {annex_title}\n\n{body}".strip()
        annexes.append(Annex(annex=annex_num, title=annex_title, references=annex_references, full=full))
    return annexes


def _chunk_paragraphs(paragraphs: list[Paragraph], chunk_size: PositiveInt, chunk_overlap: PositiveInt) -> list[Document]:
    """Split full paragraph text into smaller chunks for better retrieval."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    docs: list[Document] = []
    now = datetime.now(timezone.utc).isoformat()

    for p in paragraphs:
        # p is a Paragraph model; use its full text for splitting and preserve
        # paragraph identifier and title in metadata.
        text: str = p.full
        chunks = splitter.split_text(text) if p.full else []
        count = len(chunks)
        for idx, chunk in enumerate(chunks):
            meta = {
                "document_type": "paragraph",
                "source": "law",
                "paragraph": p.paragraph,
                "title": p.title,
                "vector_updatedAt": now,
                "chunk": idx,
                "chunk_count": count,
                "pagecontent_hash": hash_content(normalize_content(chunk)),
            }
            docs.append(Document(page_content=chunk, metadata=meta))
    return docs


def _chunk_annexes(annexes: list[Annex], chunk_size: PositiveInt, chunk_overlap: PositiveInt) -> list[Document]:
    """Split full annex text (Annex models) into smaller chunks for better retrieval.

    This preserves Annex.references in the chunk metadata.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    docs: list[Document] = []
    now = datetime.now(timezone.utc).isoformat()

    for a in annexes:
        # a is an Annex model; use a.full for splitting and keep a.references
        # attached to each chunk's metadata.
        text: str = a.full
        chunks = splitter.split_text(text) if a.full else []

        count = len(chunks)
        for idx, chunk in enumerate(chunks):
            meta = {
                "document_type": "annex",
                "source": "law",
                "annex": a.annex,
                "title": a.title,
                "references": a.references,
                "vector_updatedAt": now,
                "chunk": idx,
                "chunk_count": count,
                "pagecontent_hash": hash_content(normalize_content(chunk)),
            }
            docs.append(Document(page_content=chunk, metadata=meta))
    return docs


def _build_ids_for_documents(law_id: str, docs: list[Document]) -> list[str]:
    """Create deterministic UUID5-based IDs for each document.

    ID schema: uuid5(NAMESPACE_DNS, f"LAW-{law_id}-para-{paragraph}-chunk-{chunk}")
    """
    ids: list[str] = []
    for d in docs:
        chunk = int(d.metadata.get("chunk", 0))
        if "paragraph" in d.metadata and d.metadata["paragraph"]:
            section = f"para-{str(d.metadata['paragraph'])}"
        elif "annex" in d.metadata and d.metadata["annex"]:
            section = f"annex-{str(d.metadata['annex'])}"
        else:
            section = "body"
        name = f"LAW-{law_id}-{section}-chunk-{chunk}"
        vid: UUID = uuid5(NAMESPACE_DNS, name)
        ids.append(str(vid))
    return ids


def ingest_law(law: LawConfig, qdrant: QdrantKBClient) -> None:
    """Ingest a single law into Qdrant using the shared client.

    Steps:
      1) fetch HTML, markdownify
      2) extract paragraphs
      3) chunk content
      4) attach law-level metadata and write to Qdrant
    """
    logger.info("Starting law ingestion: %s (%s)", law.name, law.id)
    try:
        html = _fetch_html(str(law.url))
        markdown_text = md(html)

        paragraphs = _extract_paragraphs_from_markdown(markdown_text)
        annexes = _extract_annexes_from_markdown(markdown_text)
        if not paragraphs and not annexes:
            logger.warning("Law %s produced no paragraphs or annexes, skipping.", law.id)
            return

        docs_para = _chunk_paragraphs(paragraphs, law.chunk_size, law.chunk_overlap) if paragraphs else []
        docs_annex = _chunk_annexes(annexes, law.chunk_size, law.chunk_overlap) if annexes else []
        docs = [*docs_para, *docs_annex]

        # enrich with law-level metadata
        for d in docs:
            d.metadata["law_id"] = law.id
            d.metadata["law_name"] = law.name

        if not docs:
            logger.info("No chunks generated for law %s, nothing to index.", law.id)
            return

        # NOTE: snapshot creation is handled by the caller (main) to avoid
        # creating one snapshot per law. This prevents redundant snapshots
        # when ingesting multiple laws in sequence.

        ids = _build_ids_for_documents(law.id, docs)
        qdrant.add_raw_documents(docs, ids)
        logger.info("Indexed %d chunks for law %s", len(docs), law.id)
        # Reconcile Qdrant: remove stale points belonging to this law that are
        # not present in the newly generated ids. This ensures removed
        # paragraphs/annexes cannot be retrieved after re-ingestion.
        try:
            all_points = qdrant.get_all_points()
            stale_ids: list[str] = []
            for p in all_points:
                # payload is expected to contain metadata dict
                payload = p.payload or {}
                metadata = payload.get("metadata") or {}
                if metadata.get("source") == "law" and metadata.get("law_id") == law.id:
                    pid = str(p.id) if isinstance(p.id, str) else str(p.id)
                    if pid not in ids:
                        stale_ids.append(pid)
            if stale_ids:
                logger.info("Removing %d stale Qdrant points for law %s", len(stale_ids), law.id)
                qdrant.delete_points_by_ids(stale_ids)
        except Exception:
            logger.error("Failed to reconcile existing Qdrant points for law %s", law.id, exc_info=True)
    except Exception:
        logger.error("Failed to ingest law %s", law.id, exc_info=True)
        raise

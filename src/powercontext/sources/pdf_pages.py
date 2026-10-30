# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Page-level PDF sources and query-driven evidence-page retrieval."""

from __future__ import annotations

import hashlib
import io
import re
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.builtin.runtime.models import SearchMemoryRequest
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import AdapterSourceDefinition, Source, SourceMaterialization, TextEvidence
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

PDF_PAGE_SOURCE_NAME = "pdf-page"


class PDFDocumentInput(BaseModel):
    """Complete bytes of one PDF document."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("document_id must be a non-blank string")  # noqa: TRY003
        if value != value.strip():
            raise ValueError("document_id must not contain surrounding whitespace")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    """One physical PDF page and its extractable text."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_sha256: str
    page_number: int
    text: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("document_id must be a non-blank string")  # noqa: TRY003
        return value

    @field_validator("document_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("document_sha256 must be lower-case hexadecimal SHA-256")  # noqa: TRY003
        return value

    @field_validator("page_number")
    @classmethod
    def validate_page_number(cls, value: int) -> int:
        if type(value) is not int or value < 1:
            raise ValueError("page_number must be a positive integer")  # noqa: TRY003
        return value


class PDFPageSource(Source):
    """Durable captured Source for one physical PDF page."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str

    @model_validator(mode="after")
    def validate_source_identity(self) -> PDFPageSource:
        if self.source_id != self.name:
            raise ValueError("PDF page source_id must equal its Source name")  # noqa: TRY003
        return self


class PDFPageSourceAdapter:
    """Resolve parsed pages into stable Sources and read them back exactly."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one page with its document identity and physical page number."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Return a stable, bounded identity for one document revision and page."""

    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-blank string")  # noqa: TRY003
    if not isinstance(document_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", document_sha256):
        raise ValueError("document_sha256 must be lower-case hexadecimal SHA-256")  # noqa: TRY003
    if type(page_number) is not int or page_number < 1:
        raise ValueError("page_number must be a positive integer")  # noqa: TRY003
    identity = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        digest = hashlib.sha256(f"{document_id}\0{document_sha256}\0{page_number}".encode()).hexdigest()
        identity = f"pdf:{digest}"
    return identity


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page from one complete PDF, or fail atomically."""

    if not isinstance(value, PDFDocumentInput):
        raise ValueError("value must be a PDFDocumentInput")  # noqa: TRY003
    raw = bytes(value.content)
    if not raw:
        raise ValueError("PDF content must not be empty")  # noqa: TRY003
    digest = hashlib.sha256(raw).hexdigest()
    pages: list[PDFPageInput] = []
    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            if not reader.decrypt(""):
                raise ValueError("PDF requires a non-empty password")  # noqa: TRY003
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as error:
                raise ValueError(f"failed to extract page {index}") from error
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=digest,
                    page_number=index,
                    text=text,
                )
            )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF could not be parsed completely") from error
    if not pages:
        raise ValueError("PDF contains no pages")  # noqa: TRY003
    return tuple(pages)


_QUERY_STOPWORDS = frozenset(
    """
    a an and are as at be been being by can could did do does for from had has have how i if in into is it its
    me my of on or our us was were what when where which who why will with would you your the to about
    please answer question using use only shown show details detail stated state given based according
    """.split()
)
_WORD = re.compile(r"[a-z]+|\d+")


def _query_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    for token in _WORD.findall(text.lower()):
        if token in _QUERY_STOPWORDS or len(token) == 1:
            continue
        if token not in terms:
            terms.append(token)
    return tuple(terms)


_QUERY_EXPANSIONS = {
    "legal": ("proceedings", "litigation"),
    "battles": ("proceedings", "litigation", "claims"),
    "litigation": ("proceedings", "claims"),
    "geographies": ("geographic", "regions", "segments"),
    "geography": ("geographic", "regions", "segments"),
    "restructuring": ("impairment", "charges"),
    "ebitda": ("operating", "income", "depreciation", "amortization"),
    "capex": ("capital", "expenditures"),
    "revenue": ("net", "sales"),
    "margin": ("operating", "income"),
    "employees": ("headcount",),
}


def _expanded_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    expanded = list(terms)
    for term in terms:
        for synonym in _QUERY_EXPANSIONS.get(term, ()):
            if synonym not in expanded:
                expanded.append(synonym)
    return tuple(expanded)


def _search_queries(question: str) -> tuple[str, ...]:
    terms = _query_terms(question)
    if not terms:
        return (question,)
    expanded = _expanded_terms(terms)
    queries = [" ".join(terms[:4]), " ".join(terms[:8]), question]
    if expanded != terms:
        queries.append(" ".join(expanded[:10]))
        for term in terms:
            queries.extend(_QUERY_EXPANSIONS.get(term, ()))
    unique: list[str] = []
    for query in queries:
        if query.strip() and query not in unique:
            unique.append(query)
    return tuple(unique)


def _page_text(memory_text: str) -> str:
    head, separator, body = memory_text.partition("\n")
    return body if separator else memory_text


def _page_relevance(question_terms: set[str], memory_text: str) -> float:
    page = _page_text(memory_text).lower()
    tokens = _WORD.findall(page)
    if not tokens:
        return 0.0
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    overlap = [token for token in question_terms if token in counts]
    if not overlap:
        return 0.0
    coverage = len(overlap) / max(1, len(question_terms))
    frequency = sum(min(5, counts[token]) for token in overlap) / max(1, len(tokens))
    numeric_bonus = sum(1 for token in overlap if token.isdigit()) / max(1, len(overlap))
    return 3.0 * coverage + frequency + 0.2 * numeric_bonus


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Search a scoped Memory and return distinct page-level citations."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-blank string")  # noqa: TRY003
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003
    question_terms = set(_expanded_terms(_query_terms(question)))
    per_query_limit = min(200, max(limit * 4, 40))
    fused: dict[tuple[str, str, str], tuple[float, float, MemoryCitation]] = {}
    for query in _search_queries(question):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=per_query_limit))
        for rank, hit in enumerate(page.hits, start=1):
            key = (hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id)
            reciprocal = 1.0 / (60 + rank)
            relevance = _page_relevance(question_terms, hit.text)
            previous = fused.get(key)
            score = reciprocal + relevance
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            if previous is None:
                fused[key] = (score, relevance, citation)
            else:
                fused[key] = (previous[0] + score, max(previous[1], relevance), previous[2])
    ordered = sorted(fused.values(), key=lambda item: (-item[0], -item[1], item[2].entry_id))
    citations: list[MemoryCitation] = []
    seen: set[tuple[str, str, str]] = set()
    for _, _, citation in ordered:
        key = (citation.memory_ref.artifact_id, citation.entry_id, citation.entry_version_id)
        if key in seen:
            continue
        seen.add(key)
        citations.append(citation)
        if len(citations) >= limit:
            break
    return tuple(citations)


PDF_PAGE_SOURCE_ADAPTER = PDFPageSourceAdapter()
PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDF_PAGE_SOURCE_ADAPTER,
    version="1",
    projections=(PDFPageTextEvidenceProjection(),),
)

__all__ = [
    "PDF_PAGE_SOURCE_ADAPTER",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDFPageSourceAdapter",
    "PDFPageTextEvidenceProjection",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]

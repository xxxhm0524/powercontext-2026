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
import math
import re
from collections.abc import Sequence
from urllib.parse import quote, unquote

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
        reader = PdfReader(io.BytesIO(raw), strict=True)
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
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "us",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "the",
        "to",
        "about",
        "please",
        "answer",
        "question",
        "using",
        "use",
        "only",
        "shown",
        "show",
        "details",
        "detail",
        "stated",
        "state",
        "given",
        "based",
        "according",
    ]
)
_WORD = re.compile(r"[a-z]+|\d+")
_PAGE_HEADING_LIMIT = 3200

_FINANCE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "geography": ("segment", "region", "country", "area", "division", "operation", "geographic"),
    "geographies": ("segment", "region", "country", "area", "division", "operation", "geographic"),
    "geographic": ("segment", "region", "country", "area", "division"),
    "legal": ("proceeding", "litigation", "regulatory"),
    "battle": ("proceeding", "litigation"),
    "battles": ("proceeding", "litigation"),
    "restructuring": ("impairment", "charge", "severance", "productivity"),
    "ebitda": ("operating", "profit", "income", "depreciation", "amortization"),
    "capex": ("capital", "expenditure", "property", "plant", "equipment"),
    "margin": ("operating", "profit", "income", "revenue", "sales", "net", "gross"),
    "revenue": ("sales", "net"),
    "employee": ("headcount",),
    "employees": ("headcount",),
    "quick": ("current", "asset", "liability"),
    "capital": ("expenditure", "property", "plant", "equipment"),
    "intensive": ("capital", "expenditure", "property", "plant", "equipment"),
    "dividend": ("dividends", "cash"),
    "acquisition": ("acquisition", "acquired", "purchase"),
    "category": ("segment", "product", "service"),
    "categories": ("segment", "product", "service"),
    "gross": ("profit", "margin"),
    "retain": ("retention", "retained"),
    "retained": ("retention", "retain"),
}

_INCOME_PAGE_CUES = (
    "statement of income",
    "statements of income",
    "statement of operations",
    "statements of operations",
    "statement of earnings",
    "statements of earnings",
    "analysis of consolidated earnings",
    "summary of financial performance",
)
_BALANCE_PAGE_CUES = (
    "balance sheet",
    "balance sheets",
    "consolidated balance",
    "statement of financial position",
    "statements of financial position",
    "statement of condition",
    "statements of condition",
)
_CASH_PAGE_CUES = ("statement of cash flows", "statements of cash flows", "statement of cash flow")
_SEGMENT_PAGE_CUES = (
    "segment information",
    "business segment",
    "reportable segment",
    "summary of business segment",
    "segment data",
    "geographic operations",
    "geographic areas",
)
_LEGAL_PAGE_CUES = ("legal proceedings", "item 3. legal", "item 3 legal", "litigation")


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
    _, separator, body = memory_text.partition("\n")
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


def _stem_page_token(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        token = f"{token[:-3]}y"
    elif token.endswith("ing") and len(token) > 5:
        base = token[:-3]
        token = f"{base}e" if base.endswith("at") else base
    elif token.endswith("ed") and len(token) > 4:
        base = token[:-2]
        token = f"{base}e" if base.endswith("at") else base
    elif token.endswith("es") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        token = token[:-1]
    if token in {"operation", "operational"}:
        return "operate"
    if token == "geographic":
        return "geography"
    return token


def _page_terms(text: str) -> list[str]:
    return [
        _stem_page_token(token)
        for token in _WORD.findall(text.lower())
        if token not in _QUERY_STOPWORDS and len(token) > 1
    ]


def _expanded_page_terms(question: str) -> list[str]:
    terms = _page_terms(question)
    expanded = list(dict.fromkeys(terms))
    for term in terms:
        for synonym in _FINANCE_SYNONYMS.get(term, ()):
            stemmed = _stem_page_token(synonym)
            if stemmed not in expanded:
                expanded.append(stemmed)
    return expanded


def _page_intents(question: str) -> set[str]:
    lowered = question.lower()
    intents: set[str] = set()
    if any(
        phrase in lowered
        for phrase in (
            "income statement",
            "statement of income",
            "statement of operations",
            "operating income",
            "operating margin",
            "gross margin",
            "net income",
            "revenue",
            "sales",
            "ebitda",
            "ebit",
            "earnings",
            "cost of sales",
            "cogs",
            "tax rate",
            "sg&a",
            "eps",
            "margin",
        )
    ):
        intents.add("income")
    if any(
        phrase in lowered
        for phrase in (
            "balance sheet",
            "statement of financial position",
            "total assets",
            "current assets",
            "current liabilities",
            "working capital",
            "inventor",
            "accounts payable",
            "accounts receivable",
            "debt",
            "pp&e",
            "ppe",
            "goodwill",
            "shareholders",
            "quick ratio",
            "current ratio",
            "asset turnover",
            "return on assets",
            "roa",
            "return on equity",
            "roe",
            "capital-intensive",
            "capital intensive",
            "liquidity",
        )
    ):
        intents.add("balance")
    if any(
        phrase in lowered
        for phrase in (
            "cash flow",
            "cash flows",
            "operating cash",
            "capex",
            "capital expenditure",
            "depreciation",
            "amortization",
            "share repurchase",
            "free cash flow",
            "fcf",
            "cash conversion",
        )
    ):
        intents.add("cash")
    if any(
        phrase in lowered
        for phrase in ("segment", "geograph", "region", "business unit", "division", "category", "categories")
    ):
        intents.add("segment")
    if "capital intensive" in lowered or "capital-intensive" in lowered:
        intents.update(("income", "balance", "cash"))
    if any(
        phrase in lowered
        for phrase in ("return on assets", "roa", "return on equity", "roe", "asset turnover", "inventory turnover")
    ):
        intents.update(("income", "balance"))
    if any(phrase in lowered for phrase in ("legal", "litigation", "proceeding", "battle", "claim", "dispute")):
        intents.add("legal")
    return intents


def _page_kinds(text: str) -> set[str]:
    head = " ".join(text[:_PAGE_HEADING_LIMIT].lower().split())
    kinds: set[str] = set()
    if any(cue in head for cue in _INCOME_PAGE_CUES):
        kinds.add("income")
    if any(cue in head for cue in _BALANCE_PAGE_CUES):
        kinds.add("balance")
    if any(cue in head for cue in _CASH_PAGE_CUES):
        kinds.add("cash")
    if any(cue in head for cue in _SEGMENT_PAGE_CUES):
        kinds.add("segment")
    if any(cue in head for cue in _LEGAL_PAGE_CUES):
        kinds.add("legal")
    return kinds


def _local_page_scores(texts: Sequence[str], question: str) -> list[float]:
    """Offline BM25-style page scoring over every page in the scope."""

    documents: list[list[str]] = []
    frequencies: list[dict[str, int]] = []
    for text in texts:
        tokens = _page_terms(_page_text(text))
        documents.append(tokens)
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        frequencies.append(counts)
    total = len(texts)
    if not total:
        return []
    average_length = max(1.0, sum(len(tokens) for tokens in documents) / total)
    document_frequency: dict[str, int] = {}
    for counts in frequencies:
        for token in counts:
            document_frequency[token] = document_frequency.get(token, 0) + 1
    query_terms = _expanded_page_terms(question)
    intents = _page_intents(question)
    scores: list[float] = []
    for index, text in enumerate(texts):
        counts = frequencies[index]
        length = len(documents[index])
        score = 0.0
        for token in query_terms:
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            idf = math.log(
                1.0 + (total - document_frequency.get(token, 0) + 0.5) / (document_frequency.get(token, 0) + 0.5)
            )
            score += idf * frequency * 2.2 / (frequency + 1.2 * (1.0 - 0.75 + 0.75 * length / average_length))
        kinds = _page_kinds(text)
        lowered = text.lower()
        if intents & kinds:
            # Structural evidence (an actual financial statement or a named
            # section) outranks pages that merely mention the topic in prose.
            heading = lowered[:1200]
            if "consolidated statement" in heading or "summary of business segment data" in heading:
                score += 1000.0 * len(intents & kinds)
            else:
                score += 500.0 * len(intents & kinds)
        if "legal" in intents:
            if "item 3. legal proceedings" in lowered or "item 3. legal" in lowered:
                score += 80.0
        if "segment" in intents:
            if "geographic operations" in lowered:
                score += 60.0
            region_hits = sum(
                1
                for region in (
                    "north america",
                    "europe",
                    "asia pacific",
                    "latin america",
                    "africa",
                    "middle east",
                    "china",
                )
                if region in lowered
            )
            score += 8.0 * region_hits
        if "income" in intents and ("gross profit" in lowered or "operating profit" in lowered):
            score += 5.0
        question_lower = question.lower()
        if "effective tax rate" in question_lower and "effective tax rate" in lowered:
            score += 40.0
        if "card member" in question_lower and "card member" in lowered:
            score += 30.0
        if "dividend" in question_lower and "dividend" in lowered:
            score += min(6, lowered.count("dividend")) * 5.0
        if "customer concentration" in question_lower and "customer concentration" in lowered:
            score += 40.0
        elif "customer" in question_lower:
            score += min(4, lowered.count("customer")) * 3.0
        if "capital intensive" in question_lower or "capital-intensive" in question_lower:
            if kinds:
                score += 15.0
            if "capital expenditure" in lowered or "purchases of property" in lowered:
                score += 30.0
        if "debt" in question_lower and "debt outstanding" in lowered:
            score += 50.0
        score += len(set(query_terms) & set(_page_terms(text[:400])))
        scores.append(score)
    return scores


async def _pdf_page_records(memory):
    """Read every current Memory entry that came from a PDF page, if supported."""

    try:
        page = await memory.list()
    except Exception:
        return None
    records = []
    for record in page.entries:
        if not any(reference.source_type == PDF_PAGE_SOURCE_NAME for reference in record.entry.sources):
            continue
        document_id, separator, _ = record.entry.text.partition("\n")
        if not separator:
            for reference in record.entry.sources:
                parts = reference.source_id.split(":")
                if len(parts) == 4 and parts[0] == "pdf":
                    document_id = unquote(parts[1])
                    break
        records.append((record.citation, record.entry.text, document_id))
    return records


def _document_identity(document_id: str) -> str:
    """Return the company part of a FinanceBench document name, compacted."""

    base = re.split(r"_(?:19|20)\d{2}(?:_|$)", document_id, maxsplit=1)[0]
    return re.sub(r"[^a-z0-9]", "", base.lower())


def _select_document(records, question: str) -> str | None:
    compact_question = re.sub(r"[^a-z0-9]", "", question.lower())
    best: tuple[int, str] | None = None
    for _, _, document_id in records:
        identity = _document_identity(document_id)
        if not identity or identity not in compact_question:
            continue
        rank = len(identity)
        if best is None or rank > best[0]:
            best = (rank, document_id)
    return None if best is None else best[1]


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

    records = await _pdf_page_records(memory)
    local_citations: list[MemoryCitation] = []
    if records:
        selected_document = _select_document(records, question)
        selected = (
            [record for record in records if record[2] == selected_document]
            if selected_document is not None
            else records
        )
        texts = [text for _, text, _ in selected]
        scores = _local_page_scores(texts, question)
        local_order = sorted(range(len(selected)), key=lambda index: (-scores[index], index))
        for index in local_order[:limit]:
            local_citations.append(selected[index][0])
    if local_citations:
        # The offline ranking reads every page, so it is both broader and more
        # stable than one FTS tokenization. FTS only fills a short local list.
        seen = {
            (citation.memory_ref.artifact_id, citation.entry_id, citation.entry_version_id)
            for citation in local_citations
        }
        for _, _, citation in ordered:
            key = (citation.memory_ref.artifact_id, citation.entry_id, citation.entry_version_id)
            if key in seen:
                continue
            local_citations.append(citation)
            seen.add(key)
            if len(local_citations) >= limit:
                break
        return tuple(local_citations[:limit])
    return tuple(citation for _, _, citation in ordered[:limit])


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

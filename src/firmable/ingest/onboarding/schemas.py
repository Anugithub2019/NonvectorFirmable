"""Structured outputs the agent's LLM steps must return (enforced via response_schema).

Transform args are carried as a JSON string (`args_json`) because Gemini response schemas
cannot express free-form objects; the validator parses it and reports bad JSON as an issue.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResourceChoice(BaseModel):
    resource_id: str
    reason: str


class ReaderSpec(BaseModel):
    format: Literal["csv", "tsv", "xlsx", "xls", "json", "geojson"]
    encoding: str = "utf-8-sig"
    delimiter: str = ","
    sheet: str = Field("", description="sheet name for Excel; empty = first sheet")
    header_row: int = Field(0, description="0-based row index holding column names")
    skip_rows_after_header: int = 0
    records_path: str = Field("", description="dot path to the record list for JSON")


class InspectResult(BaseModel):
    what_it_is: str = Field(description="one paragraph: what this file actually contains")
    record_grain: str = Field(description="what ONE row represents, e.g. 'one licence held by "
                                          "a contractor at a point in time'")
    contains_business_entities: bool
    entity_concerns: str = Field(description="e.g. 'many rows are individuals, not businesses'")
    reader: ReaderSpec
    accept_warnings: bool = Field(False, description="true only if you have seen the parse "
                                  "warnings of THIS exact reader spec and judge them harmless")
    reasoning: str


class TransformStep(BaseModel):
    op: str
    args_json: str = Field("{}", description='JSON object of args, e.g. {"formats": ["%d/%m/%Y"]}')


class Condition(BaseModel):
    column: str
    op: Literal["equals", "in", "not_in", "matches", "not_matches", "not_empty"]
    values: list[str] = []


class FieldMapping(BaseModel):
    target: str = Field(description="canonical field, e.g. entity.legal_name, address.postcode, licence.status, related_party.abn")
    source_columns: list[str]
    join_with: str = " "
    transforms: list[TransformStep] = []
    when: list[Condition] = Field([], description="all must hold for this mapping to apply")
    confidence: float = Field(description="0-1: how sure you are this mapping is semantically "
                                          "right AND parses correctly")
    derivation: Literal["L0", "L1", "L2", "L3"]
    rationale: str


class Unmapped(BaseModel):
    column: str
    reason: str


class DateSpec(BaseModel):
    column: str = Field("", description="source column; empty = not available from records")
    transforms: list[TransformStep] = []
    note: str = ""


class RecordSpec(BaseModel):
    id_columns: list[str] = Field(description="columns that uniquely identify a raw record; "
                                              "empty list = deterministic row hash")
    id_note: str
    observed_at: DateSpec = Field(description="when the SOURCE stated the claim; if no "
                                  "per-record column, leave column empty and the dataset's "
                                  "last-modified date is used")
    valid_from: DateSpec
    valid_to: DateSpec


class MappingProposal(BaseModel):
    record: RecordSpec
    include_if: list[Condition] = Field([], description="record-level filter: rows failing "
                                        "any condition are skipped (e.g. not a business)")
    include_if_reason: str = ""
    fields: list[FieldMapping]
    unmapped: list[Unmapped]
    source_reliability: float = Field(description="0-1 trust in this publisher for these claims")
    source_reliability_reason: str
    reviewer_notes: list[str] = Field(description="things the human approver must look at")
    changes_from_previous: str = Field("", description="when revising: what you changed and why")


class CriticIssue(BaseModel):
    severity: Literal["blocking", "warning"]
    field: str
    problem: str
    suggestion: str


class CriticResult(BaseModel):
    issues: list[CriticIssue]
    summary: str

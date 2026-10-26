
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict , field_validator


class ImportantDates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: Optional[str]
    last_date: Optional[str]


class Fees(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Optional[str] = None
    currency: Optional[str] = None
    # Optional for compatibility with notices extracted before this field existed.
    type: Optional[Literal[
        "application", "admission", "registration", "examination",
        "tuition", "processing", "counselling", "other"
    ]] = None

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value):
        if value is None:
            return None

        if isinstance(value, bool):
            raise ValueError("Fee amount cannot be boolean")

        if isinstance(value, (int, float, str)):
            return str(value)

        raise ValueError("Invalid fee amount")


class NoticeSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice_type: Literal[
        "Examination",
        "Admission",
        "Scholarship",
        "Discipline",
        "Administrative",
        "Academic Calendar",
        "General"
    ]

    title: str
    reference_no: Optional[str]
    issue_date: Optional[str]
    target_audience: Optional[str]
    important_dates: ImportantDates
    fees: Fees
    action_required: Optional[str]
    # Empty on older notice records; never infer a document list.
    required_documents: List[str] = Field(default_factory=list)
    key_points: List[str]
    issued_by: Optional[str]
    summary: str

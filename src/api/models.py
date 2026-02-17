"""Pydantic models for API request/response."""
from typing import Optional
from pydantic import BaseModel


class ScrapeRequest(BaseModel):
    url: str
    source_id: str = ""
    source_name: str = ""
    max_pages: int = 10


class SourceCreate(BaseModel):
    url: str
    name: str = ""
    schedule_hours: int = 12


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    schedule_hours: Optional[int] = None
    max_pages: Optional[int] = None
    notes: Optional[str] = None


class SourceReorder(BaseModel):
    source_ids: list[str]


class QueryCreate(BaseModel):
    query: str


class QueryUpdate(BaseModel):
    query: Optional[str] = None
    enabled: Optional[bool] = None


class BaserowConfig(BaseModel):
    api_url: str = ""
    api_token: str = ""
    table_id: int = 0


class FieldMappingUpdate(BaseModel):
    field_mapping: dict


class SettingsUpdate(BaseModel):
    scraping: Optional[dict] = None
    jpeg: Optional[dict] = None
    scheduler: Optional[dict] = None
    gallery: Optional[dict] = None
    ai: Optional[dict] = None

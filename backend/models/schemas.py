from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any, Literal
from datetime import datetime


class Cloud(BaseModel):
    account_id: Optional[str] = None
    region: Optional[str] = None
    service: Optional[str] = None


class NormalizedLog(BaseModel):
    """Central normalized schema per spec.md section 3"""
    model_config = ConfigDict(populate_by_name=True)

    timestamp: str = Field(alias="@timestamp")
    tenant: str
    source: Literal["firewall", "crowdstrike", "aws", "m365", "ad", "api", "network"]
    vendor: Optional[str] = None
    product: Optional[str] = None
    event_type: str
    event_subtype: Optional[str] = None
    severity: int = Field(ge=0, le=10, default=5)
    action: Optional[Literal["allow", "deny", "create", "delete", "login", "logout", "alert", "quarantine", "block", "detect", "prevent", "notify"]] = None
    src_ip: Optional[str] = None
    src_port: Optional[int] = None
    dst_ip: Optional[str] = None
    dst_port: Optional[int] = None
    protocol: Optional[str] = None
    user: Optional[str] = None
    host: Optional[str] = None
    process: Optional[str] = None
    url: Optional[str] = None
    http_method: Optional[str] = None
    status_code: Optional[int] = None
    rule_name: Optional[str] = None
    rule_id: Optional[str] = None
    cloud: Optional[Cloud] = None
    raw: Optional[Any] = None
    # Spec §3 names this field "_tags" with a leading underscore, but Pydantic
    # v2 treats underscore-prefixed names as private attributes and silently
    # drops the value on validation. Use a real field name internally with
    # _tags as both the input and output alias so the on-the-wire contract
    # (and DB column name) stays unchanged.
    tags: List[str] = Field(default=[], alias="_tags", serialization_alias="_tags")


class LogIngest(BaseModel):
    tenant: str
    source: str
    event_type: str
    user: Optional[str] = None
    ip: Optional[str] = None
    reason: Optional[str] = None
    host: Optional[str] = None
    process: Optional[str] = None
    severity: Optional[int] = Field(default=None, ge=0, le=10)
    action: Optional[str] = None
    logon_type: Optional[int] = None
    event_id: Optional[int] = None
    workload: Optional[str] = None
    status: Optional[str] = None
    cloud: Optional[Cloud] = None
    raw: Optional[Any] = None
    timestamp: Optional[str] = Field(default=None, alias="@timestamp")


class AlertRule(BaseModel):
    id: Optional[int] = None
    # tenant="*" creates a global rule that fires for every tenant's logs;
    # otherwise the rule is scoped to that specific tenant only (spec §6).
    tenant: Optional[str] = None
    name: str
    description: Optional[str] = None
    event_types: List[str] = ["LogonFailed", "app_login_failed"]
    threshold: int = 5
    window_minutes: int = 5
    group_by: str = "src_ip"
    action: Literal["webhook", "email", "both", "store"] = "store"
    webhook_url: Optional[str] = None
    email_to: Optional[str] = None
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TriggeredAlert(BaseModel):
    id: Optional[int] = None
    rule_id: int
    rule_name: str
    group_key: str
    src_ip: str
    count: int = 1
    unique_count: int = 1
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    first_seen: datetime
    last_seen: datetime
    tenant: str
    source: Optional[str] = None
    event_type: Optional[str] = None
    logs: List[int] = []
    acknowledged: bool = False
    triggered_at: Optional[datetime] = None


class User(BaseModel):
    id: Optional[int] = None
    username: str
    email: Optional[str] = None
    role: Literal["Admin", "Viewer"] = "Viewer"
    tenant: str
    hashed_password: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class TimelineBucket(BaseModel):
    bucket: str  # ISO8601 timestamp
    count: int


class TopItem(BaseModel):
    key: str
    count: int


class DashboardStats(BaseModel):
    total: int
    timeline: List[TimelineBucket]
    top_src_ips: List[TopItem]
    top_users: List[TopItem]
    top_event_types: List[TopItem]
    by_source: List[TopItem]
    by_severity: List[TopItem]


class TenantStats(BaseModel):
    total: int
    by_source: List[TopItem]
    by_severity: List[TopItem]

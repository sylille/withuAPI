"""Request / response schemas for the WithU Talk AI inference server (AI 추론 서버).

Privacy: identifiers are pseudonymous `participant_code`s only — no real names, phone
numbers, or school names should ever be sent (per the design doc's minimum-info rule).

v0.3.0: + message_id, track_bystander, incident_id, bystander_state (방관행동 판정부)
        + attribution / suppressed / guard_reason declared so they are no longer dropped
"""
from typing import Any, List, Optional, Dict
from pydantic import BaseModel, Field


class Message(BaseModel):
    participant_code: str = Field(..., description="pseudonymous speaker id (NOT a real name)")
    text: str = ""
    timestamp: Optional[str] = None
    message_id: Optional[str] = None                # NEW: lets reactions / read receipts point at messages
    read_by_count: Optional[int] = None            # for exclusion / 방관 signals
    response_latency_sec: Optional[float] = None    # seconds until this speaker responded
    is_defense_action: bool = False
    reply_to_message_id: Optional[str] = None

class Participant(BaseModel):
    participant_code: str
    display_name: str = ""
    aliases: List[str] = Field(default_factory=list)

class AnalyzeRequest(BaseModel):
    room_id: str
    context: List[Message] = Field(default_factory=list, description="recent window, oldest→newest")
    new_message: Message
    participants: List[Participant] = Field(default_factory=list)
    has_image: bool = False
    left_chat: bool = False
    # optional live-log metadata for the exclusion module (Module C) and 방관 log-rule
    logs: Optional[Dict] = None
    # NEW: False on the fast pre-send call, True (default) on the post-send call.
    # Each message must be tracked exactly once or incidents/bystanders are double-counted.
    track_bystander: bool = True


class AnalyzeResponse(BaseModel):
    room_id: str
    cb_score: float = Field(..., ge=0.0, le=1.0, description="ensemble cyberbullying possibility")
    cb_type: str = Field(..., description="비해당 | 언어적 폭력 | 시각적 폭력 | 배제 | composite")
    intervention_level: str = Field(..., description="none | suspect | confirm")
    intervention_needed: bool
    attribution: Optional[Dict[str, Any]] = None
    suppressed: bool = False
    guard_reason: str = "none"
    bystander_behavior: Optional[str] = Field(None, description="방어 | 동조 | 방관 | None (only when CB active)")
    module_scores: Dict[str, Optional[float]]
    evidence: str
    incident_id: Optional[str] = None                        # NEW
    bystander_state: Optional[Dict[str, Any]] = None         # NEW: incident + per-bystander stage
    participants: List[Participant] = Field(default_factory=list)


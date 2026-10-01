# -*- coding: utf-8 -*-
"""FastAPI routes for the 방관행동 판정부.

    POST /bystander/events    app/messenger server reports read / leave / reaction / defense events
    GET  /bystander/actions   poll queued nudges for a room (each action is returned once)
    GET  /bystander/state     current incident + per-bystander state (debug / research log)
"""
from typing import Literal, Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .bystander import BystanderTracker

tracker = BystanderTracker()          # one instance per server process (run uvicorn with 1 worker)
router = APIRouter(prefix="/bystander", tags=["bystander"])

EventType = Literal["read", "room_open", "join", "leave", "reaction", "reaction_cancel",
                    "defense_action", "summary_shown", "decline", "not_bullying"]


class BystanderEvent(BaseModel):
    room_id: str
    participant_code: str = Field(..., description="pseudonymous code of the child who did something")
    type: EventType
    timestamp: Optional[str] = Field(None, description="ISO 8601; server time if omitted")
    message_id: Optional[str] = Field(None, description="read: last message shown on screen")
    unread_count: Optional[int] = Field(None, description="read/room_open: unread messages when opening the room")
    target_message_id: Optional[str] = Field(None, description="reaction: message that was reacted to")
    target_participant_code: Optional[str] = Field(None, description="reaction: sender of that message")
    reaction: Optional[str] = Field(None, description="reaction: like|empathy|laugh|dislike|angry|sad ...")
    normal: bool = Field(True, description="leave: False for crash / network drop / app killed")
    kind: Optional[str] = Field(None, description="defense_action: comfort_dm|stop_dm|tell_adult|topic_change|report")


@router.post("/events")
def post_event(ev: BystanderEvent):
    actions = tracker.on_event(ev.model_dump())
    return {"ok": True, "actions": actions}


@router.get("/actions")
def get_actions(room_id: str = Query(...)):
    return {"room_id": room_id, "actions": tracker.drain(room_id)}


@router.get("/state")
def get_state(room_id: str = Query(...), participant_code: Optional[str] = None):
    return {"room_id": room_id, "incident": tracker.state(room_id, participant_code)}

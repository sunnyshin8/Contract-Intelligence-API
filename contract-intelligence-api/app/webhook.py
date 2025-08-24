from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import aiohttp
import asyncio
import json
import logging
from datetime import datetime

from models import WebhookConfig
from logging_config import get_logger, log_event

logger = get_logger("webhook")

router = APIRouter(
    prefix="/webhook",
    tags=["webhook"],
    responses={404: {"description": "Not found"}},
)

webhooks = {}


class WebhookRegisterRequest(BaseModel):
    url: str
    events: List[str]


class WebhookRegisterResponse(BaseModel):
    id: str
    url: str
    events: List[str]


async def send_webhook_notification(webhook_url: str, event_type: str, payload: Dict[str, Any]):
    """Send webhook notification to the registered URL."""
    try:
        event_data = {
            "event": event_type,
            "timestamp": datetime.now().isoformat(),
            "payload": payload
        }
        
        log_event("webhook_notification_sending", {
            "event_type": event_type,
            "webhook_url_domain": webhook_url.split('/')[2] if '//' in webhook_url else "unknown"
        }, "webhook")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=event_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status < 200 or response.status >= 300:
                    logger.error(f"Failed to send webhook to {webhook_url}. Status: {response.status}")
                    log_event("webhook_notification_failed", {
                        "event_type": event_type,
                        "status_code": response.status,
                        "webhook_url_domain": webhook_url.split('/')[2] if '//' in webhook_url else "unknown"
                    }, "webhook")
                    return False
                
                log_event("webhook_notification_sent", {
                    "event_type": event_type,
                    "status_code": response.status
                }, "webhook")
                return True
    except Exception as e:
        logger.error(f"Error sending webhook to {webhook_url}: {str(e)}")
        log_event("webhook_notification_error", {
            "event_type": event_type,
            "error": str(e)
        }, "webhook")
        return False


@router.post("/register", response_model=WebhookRegisterResponse)
async def register_webhook(request: WebhookRegisterRequest):
    """
    Register a webhook URL to receive event notifications.
    
    Supported events:
    - ingest.complete
    - extract.complete
    - ask.complete
    - audit.complete
    """
    import uuid
    webhook_id = str(uuid.uuid4())
    
    webhooks[webhook_id] = {
        "url": request.url,
        "events": request.events
    }
    
    log_event("webhook_registered", {
        "webhook_id": webhook_id,
        "events": request.events,
        "url_domain": request.url.split('/')[2] if '//' in request.url else "unknown"
    }, "webhook")
    
    return WebhookRegisterResponse(
        id=webhook_id,
        url=request.url,
        events=request.events
    )


@router.delete("/unregister/{webhook_id}")
async def unregister_webhook(webhook_id: str):
    """Unregister a webhook by ID."""
    if webhook_id not in webhooks:
        logger.warning(f"Attempt to unregister non-existent webhook: {webhook_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Webhook {webhook_id} not found"
        )
    
    log_event("webhook_unregistered", {
        "webhook_id": webhook_id
    }, "webhook")
    
    del webhooks[webhook_id]
    return {"message": f"Webhook {webhook_id} unregistered successfully"}


@router.get("/list")
async def list_webhooks():
    """List all registered webhooks."""
    return [
        {"id": webhook_id, **webhook_data}
        for webhook_id, webhook_data in webhooks.items()
    ]


def trigger_webhook_event(event_type: str, payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """Trigger webhook event to all subscribed webhooks."""
    subscribed_webhooks = []
    
    for webhook_id, webhook_data in webhooks.items():
        if event_type in webhook_data["events"]:
            subscribed_webhooks.append(webhook_id)
            background_tasks.add_task(
                send_webhook_notification,
                webhook_data["url"],
                event_type,
                payload
            )
    
    log_event("webhook_event_triggered", {
        "event_type": event_type,
        "subscribed_webhooks_count": len(subscribed_webhooks)
    }, "webhook")

"""
CoachAI — Billing (Stripe).

Flow:
  1. POST /billing/checkout → creates a Stripe Checkout Session for the £10/mo
     Pro price, returns a URL the frontend redirects to.
  2. Stripe redirects back on success; the subscription becomes active.
  3. POST /billing/webhook → Stripe calls this on subscription lifecycle events;
     we flip user.plan accordingly. The webhook is the source of truth, NOT the
     redirect (users can close the tab; webhooks are reliable).
"""
from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter()
stripe.api_key = settings.stripe_secret_key


@router.post("/billing/checkout")
async def create_checkout(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email, metadata={"user_id": user.id})
        user.stripe_customer_id = customer.id
        await db.commit()

    checkout = stripe.checkout.Session.create(
        customer=user.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id_pro, "quantity": 1}],
        success_url="https://app.coachai.gg/subscription?status=success",
        cancel_url="https://app.coachai.gg/subscription?status=cancel",
        metadata={"user_id": user.id},
    )
    return {"checkout_url": checkout.url}


@router.post("/billing/portal")
async def billing_portal(user: User = Depends(current_user)):
    """Stripe-hosted portal so users manage/cancel their own subscription."""
    if not user.stripe_customer_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No billing account")
    portal = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url="https://app.coachai.gg/subscription",
    )
    return {"portal_url": portal.url}


@router.post("/billing/webhook")
async def webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid webhook signature")

    etype = event["type"]
    obj = event["data"]["object"]

    async def set_plan(customer_id: str, plan: str):
        user = (await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )).scalar_one_or_none()
        if user:
            user.plan = plan
            await db.commit()

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        status_active = obj.get("status") in ("active", "trialing")
        await set_plan(obj["customer"], "pro" if status_active else "free")
    elif etype == "customer.subscription.deleted":
        await set_plan(obj["customer"], "free")

    return {"received": True}

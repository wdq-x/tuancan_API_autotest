# -*- coding: utf-8 -*-
"""Reusable, API-only fixtures for isolated regression data."""
from datetime import date, timedelta
from typing import Any, Dict, Optional
from uuid import uuid4

from utils.api_test_support import assert_success


CHANNELS_URL = "/v1/channels"
CHANNEL_META_URL = "/v1/channels/meta"
CUSTOMERS_URL = "/v1/customers"


def create_active_channel(client, prefix: str) -> Dict[str, Any]:
    """Create one sales-managed, active channel that can be used as a lead source."""
    meta = assert_success(client.get(CHANNEL_META_URL), "get AT channel creation metadata")
    owners = (meta.get("data") or {}).get("owners") or []
    owner_id = next(
        (
            item.get("id")
            for item in owners
            if isinstance(item, dict) and isinstance(item.get("id"), int) and item["id"] > 0
        ),
        None,
    )
    assert owner_id, "No active owner is available to create AT fixture channel: %s" % meta

    name = "%s-%s" % (prefix, uuid4().hex[:12])
    payload = assert_success(
        client.post(
            CHANNELS_URL,
            json={
                "name": name,
                "channel_type": "partner",
                "owner_id": owner_id,
                "cooperation_status": "active",
                "start_date": date.today().isoformat(),
                "contact_person": "API automation",
                "contact_phone": "13800000000",
                "channel_cost": "0.00",
                "remark": "AT isolated API regression fixture; safe to delete",
            },
        ),
        "create AT active channel",
    )
    channel = payload.get("data") or {}
    assert isinstance(channel.get("id"), int) and channel["id"] > 0, payload
    assert channel.get("name") == name, payload
    assert channel.get("cooperation_status") == "active", payload
    return channel


def delete_channel(client, channel_id: Optional[int]) -> None:
    """Delete an AT channel after all its child leads and customers have been removed."""
    if channel_id:
        assert_success(client.delete("%s/%s" % (CHANNELS_URL, channel_id)), "delete AT active channel")


def create_normal_customer(client, prefix: str, channel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a normal, no-external-call customer with an optional AT channel relation."""
    name = "%s-%s" % (prefix, uuid4().hex[:12])
    body: Dict[str, Any] = {
        "name": name,
        "deployment_type": "public_cloud",
        "customer_type": "school",
        "manager_name": "API automation",
        "manager_phone": "13900000000",
        "service_period": 12,
        "valid_start": date.today().isoformat(),
        "valid_end": (date.today() + timedelta(days=365)).isoformat(),
        "dining_limit": 1,
        "pos_count": 1,
        "remarks": "AT isolated API regression fixture; safe to delete",
        "attachments": [],
        "call_domain_api": False,
    }
    if channel:
        body.update(
            {
                "channel_id": channel["id"],
                "channel_name": channel["name"],
                "channel_contact": "API automation",
                "channel_phone": "13800000000",
            }
        )

    payload = assert_success(client.post(CUSTOMERS_URL, json=body), "create AT normal customer")
    customer = payload.get("data") or {}
    assert isinstance(customer.get("id"), int) and customer["id"] > 0, payload
    assert customer.get("name") == name, payload
    assert customer.get("status") == "normal", payload
    if channel:
        assert customer.get("channel_id") == channel["id"], payload
    return customer


def delete_customer(client, customer_id: Optional[int]) -> None:
    """Soft-delete an AT customer after dependent test projects have been removed."""
    if customer_id:
        assert_success(client.delete("%s/%s" % (CUSTOMERS_URL, customer_id)), "delete AT normal customer")

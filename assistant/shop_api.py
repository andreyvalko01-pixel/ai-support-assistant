"""Звернення до API магазину: статус замовлення і заявка на повернення.

Якщо SHOP_API_URL не задано, працюємо з невеликим демо-набором замовлень,
щоб можна було перевірити сценарії без справжнього магазину.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from .config import settings

STATUS_TEXT = {
    "new": "прийняте, готуємо до відправки",
    "packed": "зібране на складі, сьогодні передамо в доставку",
    "shipped": "відправлене",
    "delivered": "доставлене",
    "cancelled": "скасоване",
}

RETURN_DAYS = 14


@dataclass
class OrderInfo:
    number: str
    status: str
    phone_tail: str
    delivered_at: date | None = None
    ttn: str | None = None


_today = date.today()
DEMO_ORDERS = {
    "10452": OrderInfo("10452", "shipped", "4567", ttn="20450012345678"),
    "10398": OrderInfo("10398", "delivered", "1122", delivered_at=_today - timedelta(days=3)),
    "10211": OrderInfo("10211", "delivered", "9900", delivered_at=_today - timedelta(days=30)),
    "10477": OrderInfo("10477", "packed", "3344"),
}


class ShopApiError(Exception):
    pass


def get_order(number: str) -> OrderInfo | None:
    if not settings.shop_api_url:
        return DEMO_ORDERS.get(number)

    resp = httpx.get(
        f"{settings.shop_api_url}/orders/{number}",
        headers={"Authorization": f"Bearer {settings.shop_api_token}"},
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise ShopApiError(f"HTTP {resp.status_code}")
    data = resp.json()
    return OrderInfo(
        number=str(data["id"]),
        status=data["status"],
        phone_tail=data["phone"][-4:],
        delivered_at=date.fromisoformat(data["delivered_at"][:10]) if data.get("delivered_at") else None,
        ttn=data.get("ttn"),
    )


def describe_order(order: OrderInfo) -> str:
    text = f"Замовлення №{order.number} {STATUS_TEXT.get(order.status, order.status)}."
    if order.ttn:
        text += f" ТТН Нової пошти: {order.ttn}."
    return text


def create_return(order: OrderInfo, reason: str) -> str:
    """Повертає номер заявки на повернення або кидає ValueError з поясненням, чому не можна."""
    if order.status != "delivered" or not order.delivered_at:
        raise ValueError("Оформити повернення можна після отримання замовлення.")
    if (date.today() - order.delivered_at).days > RETURN_DAYS:
        raise ValueError(f"Минуло більше {RETURN_DAYS} днів з отримання, тут потрібне рішення менеджера.")

    if not settings.shop_api_url:
        return f"R-{order.number}"

    resp = httpx.post(
        f"{settings.shop_api_url}/returns",
        json={"order_id": order.number, "reason": reason},
        headers={"Authorization": f"Bearer {settings.shop_api_token}"},
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        raise ShopApiError(f"HTTP {resp.status_code}")
    return resp.json()["id"]

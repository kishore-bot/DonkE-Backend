from datetime import date

from pydantic import BaseModel


class WalletView(BaseModel):
    coins: int


class CatalogItem(BaseModel):
    sku: str
    label: str
    slot: str
    price: int
    owned: bool
    equipped: bool
    festival: str | None = None
    available: bool = True
    available_until: date | None = None

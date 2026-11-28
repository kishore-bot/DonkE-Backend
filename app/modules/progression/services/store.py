from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.core.platform import Platform
from app.modules.progression.helpers.catalog import (
    CATALOG,
    SQUAD_COSMETIC,
    in_window,
    window_end,
)
from app.modules.progression.models.cosmetic import Cosmetic
from app.modules.progression.models.wallet import Wallet
from app.modules.progression.repositories.economy import (
    credit,
    own,
    wallet_lock,
)
from app.modules.progression.schemas.store import CatalogItem

EARNED_COSMETICS = {
    "tier": "Season tier",
    "bonus": "Streak bonus",
    "season": "Season reward",
}


def cosmetic_slot(sku: str) -> str:
    entry = CATALOG.get(sku)
    return entry.slot if entry else sku.rsplit(":", 1)[-1]


def earned_cosmetic(sku: str, item: Cosmetic) -> CatalogItem:
    origin = sku.split(":", 1)[0]
    slot = cosmetic_slot(sku)
    label = (
        SQUAD_COSMETIC
        if origin == "squad"
        else f"{EARNED_COSMETICS.get(origin, 'Earned')} {slot.replace('_', ' ')}"
    )
    return CatalogItem(
        sku=sku,
        label=label,
        slot=slot,
        price=0,
        owned=True,
        equipped=item.equipped,
        available=False,
    )


class StoreService:
    def __init__(self, platform: Platform):
        self.platform = platform

    async def balance(self, player: UUID) -> int:
        async with self.platform.sessions() as db:
            value = await db.get(Wallet, player)
            return value.coins if value else 0

    async def inventory(self, player: UUID) -> list[str]:
        async with self.platform.sessions() as db:
            return list(
                await db.scalars(
                    select(Cosmetic.sku)
                    .where(Cosmetic.player_id == player)
                    .order_by(Cosmetic.sku)
                )
            )

    async def catalog(self, player: UUID) -> list[CatalogItem]:
        async with self.platform.sessions() as db:
            owned = {
                item.sku: item
                for item in await db.scalars(
                    select(Cosmetic).where(Cosmetic.player_id == player)
                )
            }
        today = datetime.now(UTC).date()
        standard = [
            CatalogItem(
                sku=sku,
                label=item.label,
                slot=item.slot,
                price=item.price,
                owned=sku in owned,
                equipped=sku in owned and owned[sku].equipped,
                festival=item.festival,
                available=in_window(item.window, today),
                available_until=window_end(item.window, today),
            )
            for sku, item in CATALOG.items()
        ]
        return standard + [
            earned_cosmetic(sku, item)
            for sku, item in sorted(owned.items())
            if sku not in CATALOG
        ]

    async def buy(self, player: UUID, sku: str) -> int:
        product = CATALOG.get(sku)
        if product is None:
            raise AppError(404, "cosmetic_not_found", "Cosmetic not found")
        async with self.platform.sessions.begin() as db:
            wallet = await wallet_lock(db, player)
            if await db.get(Cosmetic, (player, sku)) is not None:
                return wallet.coins
            if not in_window(product.window, datetime.now(UTC).date()):
                raise AppError(
                    409,
                    "cosmetic_unavailable",
                    f"{product.label} returns for {product.festival}",
                )
            if wallet.coins < product.price:
                raise AppError(
                    409, "insufficient_coins", "Earn more coins to buy this cosmetic"
                )
            # The ledger reference is unique per player and item. If it already
            # exists, the item was paid for, so restore it without charging twice.
            await credit(db, wallet, f"buy:{player}:{sku}", "purchase", -product.price)
            await own(db, player, sku)
            return wallet.coins

    async def equip(self, player: UUID, sku: str) -> None:
        async with self.platform.sessions.begin() as db:
            await wallet_lock(db, player)
            owned = list(
                await db.scalars(select(Cosmetic).where(Cosmetic.player_id == player))
            )
            selected = next((item for item in owned if item.sku == sku), None)
            if selected is None:
                raise AppError(
                    404, "cosmetic_not_owned", "Cosmetic not found in inventory"
                )

            slot = cosmetic_slot(sku)
            for item in owned:
                if cosmetic_slot(item.sku) == slot:
                    item.equipped = item.sku == sku

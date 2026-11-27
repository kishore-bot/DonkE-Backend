from typing import Annotated

from fastapi import APIRouter, Path

from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.progression.dependencies import Store
from app.modules.progression.schemas import (
    CatalogItem,
    WalletView,
)

router = APIRouter()

Sku = Annotated[str, Path(min_length=1, max_length=80)]


@router.get("/store/wallet")
async def balance(player: CurrentPlayer, progress: Store) -> WalletView:
    return WalletView(coins=await progress.balance(player.profile.id))


@router.get("/store/catalog")
async def catalog(player: CurrentPlayer, progress: Store) -> list[CatalogItem]:
    return await progress.catalog(player.profile.id)


@router.get("/store/inventory")
async def inventory(player: CurrentPlayer, progress: Store) -> list[str]:
    return await progress.inventory(player.profile.id)


@router.post("/store/{sku}/buy", dependencies=PlayerWrites)
async def buy(sku: Sku, player: CurrentPlayer, progress: Store) -> WalletView:
    return WalletView(coins=await progress.buy(player.profile.id, sku))


@router.put("/store/{sku}/equip", status_code=204, dependencies=PlayerWrites)
async def equip(sku: Sku, player: CurrentPlayer, progress: Store) -> None:
    await progress.equip(player.profile.id, sku)

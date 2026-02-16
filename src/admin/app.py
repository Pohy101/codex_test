from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.admin.store import BridgePairStore, StoredBridgePair
from src.bridge.service import BridgeService


class BridgePairPayload(BaseModel):
    discord_channel_id: int
    telegram_chat_id: int


class BridgePairResponse(BridgePairPayload):
    id: str


class AdminContext:
    def __init__(
        self,
        *,
        bridge_service: BridgeService,
        bridge_pair_store: BridgePairStore,
        admin_token: str | None,
    ) -> None:
        self.bridge_service = bridge_service
        self.bridge_pair_store = bridge_pair_store
        self.admin_token = admin_token


def create_admin_app(context: AdminContext) -> FastAPI:
    app = FastAPI(title="Bridge Admin")

    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def _require_admin_auth(authorization: str | None = Header(default=None)) -> None:
        if not context.admin_token:
            return

        expected = f"Bearer {context.admin_token}"
        if authorization != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/")
    async def index(_: None = Depends(_require_admin_auth)) -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/bridge-pairs", response_model=list[BridgePairResponse])
    async def list_bridge_pairs(_: None = Depends(_require_admin_auth)) -> list[BridgePairResponse]:
        pairs = context.bridge_pair_store.load()
        return [BridgePairResponse(**pair.__dict__) for pair in pairs]

    @app.post("/api/bridge-pairs", response_model=BridgePairResponse, status_code=status.HTTP_201_CREATED)
    async def create_bridge_pair(
        payload: BridgePairPayload,
        _: None = Depends(_require_admin_auth),
    ) -> BridgePairResponse:
        from uuid import uuid4

        pairs = context.bridge_pair_store.load()
        created = StoredBridgePair(
            id=str(uuid4()),
            discord_channel_id=payload.discord_channel_id,
            telegram_chat_id=payload.telegram_chat_id,
        )
        pairs.append(created)
        context.bridge_pair_store.save(pairs)
        await context.bridge_service.update_bridge_pairs(tuple(pair.to_bridge_pair() for pair in pairs))
        return BridgePairResponse(**created.__dict__)

    @app.put("/api/bridge-pairs/{pair_id}", response_model=BridgePairResponse)
    async def update_bridge_pair(
        pair_id: str,
        payload: BridgePairPayload,
        _: None = Depends(_require_admin_auth),
    ) -> BridgePairResponse:
        pairs = context.bridge_pair_store.load()
        for idx, pair in enumerate(pairs):
            if pair.id == pair_id:
                updated = StoredBridgePair(
                    id=pair.id,
                    discord_channel_id=payload.discord_channel_id,
                    telegram_chat_id=payload.telegram_chat_id,
                )
                pairs[idx] = updated
                context.bridge_pair_store.save(pairs)
                await context.bridge_service.update_bridge_pairs(
                    tuple(item.to_bridge_pair() for item in pairs)
                )
                return BridgePairResponse(**updated.__dict__)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bridge pair not found")

    @app.delete("/api/bridge-pairs/{pair_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_bridge_pair(pair_id: str, _: None = Depends(_require_admin_auth)) -> Response:
        pairs = context.bridge_pair_store.load()
        kept_pairs = [pair for pair in pairs if pair.id != pair_id]
        if len(kept_pairs) == len(pairs):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bridge pair not found")

        context.bridge_pair_store.save(kept_pairs)
        await context.bridge_service.update_bridge_pairs(tuple(pair.to_bridge_pair() for pair in kept_pairs))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app

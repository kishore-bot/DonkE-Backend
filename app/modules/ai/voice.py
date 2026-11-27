import base64
import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.modules.admin import flags
from app.modules.ai.gateway import Gateway

SCRIPT = Path(__file__).with_name("voice.lua").read_text(encoding="utf-8")
VOICES = {"kore": "Kore", "puck": "Puck", "leda": "Leda", "aoede": "Aoede"}


async def enabled(gateway: Gateway) -> bool:
    if gateway.provider is None:
        return False
    values = await flags.current(gateway.platform)
    return values["ai_enabled"] and values["commentary_enabled"]


class Voice:
    def __init__(self, gateway: Gateway):
        self.gateway = gateway
        self.redis = gateway.platform.redis
        self.script = self.redis.register_script(SCRIPT)

    def identifier(self, text: str, language: str, voice: str) -> str:
        model = self.gateway.platform.settings.gemini_voice_model
        return sha256(json.dumps([model, language, voice, text]).encode()).hexdigest()

    async def execute(self, action: str, **fields: str | int) -> dict:
        value = await self.script(
            keys=[self.gateway.key("media")], args=[action, json.dumps(fields)]
        )
        return json.loads(value)

    async def enqueue(self, text: str, language: str, voice: str) -> str:
        identifier = self.identifier(text, language, voice)
        result = await self.execute(
            "enqueue", id=identifier, text=text, voice=VOICES[voice]
        )
        return result["status"]

    async def clip(self, text: str, language: str, voice: str) -> bytes | None:
        identifier = self.identifier(text, language, voice)
        data = await self.redis.get(self.gateway.key(f"media:voice:clip:{identifier}"))
        return base64.b64decode(data) if data else None

    async def tick(self) -> bool:
        if not await enabled(self.gateway):
            return False
        owner = uuid4().hex
        job = await self.execute(
            "claim",
            owner=owner,
            concurrency=self.gateway.platform.settings.voice_concurrency,
        )
        if not job:
            return False
        audio = await self.gateway.call(
            "speech",
            lambda provider: provider.render(job["text"], job["voice"]),
            voice=True,
        )
        if (
            audio
            and 12 < len(audio) <= 1_000_000
            and audio[:4] == b"RIFF"
            and audio[8:12] == b"WAVE"
        ):
            await self.execute(
                "complete",
                owner=owner,
                id=job["id"],
                clip=base64.b64encode(audio).decode(),
            )
        else:
            await self.execute("retry", owner=owner, id=job["id"])
        return True

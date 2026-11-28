import base64

from app.core.config import Settings
from app.modules.ai.dto.provider import Models, Selected, Written
from app.modules.ai.schemas.provider import Choice


class Gemini:
    """Google Gemini through google-genai: text, TTS and embeddings."""

    def __init__(self, settings: Settings):
        from google import genai
        from google.genai import types
        from pydantic_ai import Agent, NativeOutput
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        assert settings.gemini_api_key is not None
        self.settings = settings
        self.models = Models(
            text=settings.gemini_text_model,
            voice=settings.gemini_voice_model,
            embedding=settings.gemini_embedding_model,
        )
        self.client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_options=types.HttpOptions(api_version="v1beta"),
        )
        self.coach = Agent(
            GoogleModel(
                settings.gemini_text_model, provider=GoogleProvider(client=self.client)
            ),
            output_type=NativeOutput(Choice),
            instructions="Choose one exact rule key from the candidate rules. Return that key only.",
            retries=0,
            model_settings={"max_tokens": 120},
        )

    async def close(self) -> None:
        try:
            await self.client.aio.aclose()
        finally:
            self.client.close()

    async def select(self, task: str, prompt: str) -> Selected:
        if task == "coach":
            answer = await self.coach.run(prompt)
            return Selected(answer.output.key, answer.usage.total_tokens)
        from google.genai import types

        reply = await self.client.aio.models.generate_content(
            model=self.settings.gemini_text_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=Choice,
                max_output_tokens=120,
            ),
        )
        choice = Choice.model_validate_json(reply.text or "")
        usage = reply.usage_metadata
        return Selected(choice.key, (usage.total_token_count or 0) if usage else 0)

    async def write(self, task: str, prompt: str) -> Written:
        from google.genai import types

        reply = await self.client.aio.models.generate_content(
            model=self.settings.gemini_text_model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=200, temperature=0.8),
        )
        usage = reply.usage_metadata
        return Written(
            (reply.text or "").strip(), (usage.total_token_count or 0) if usage else 0
        )

    async def render(self, text: str, voice: str) -> bytes:
        response = await self.client.aio.interactions.create(
            model=self.settings.gemini_voice_model,
            input=[
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": text,
                            "annotations": [
                                {
                                    "type": "speech_metadata",
                                    "style": "Warm, clear and friendly",
                                }
                            ],
                        }
                    ],
                }
            ],
            response_format={"type": "audio", "mime_type": "audio/wav"},
            generation_config={"speech_config": [{"voice": voice}]},
            stream=False,
        )
        audio = getattr(response, "output_audio", None)
        if not audio or not audio.data:
            raise ValueError("TTS did not produce audio")
        return base64.b64decode(audio.data, validate=True)

    async def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        from google.genai import types

        response = await self.client.aio.models.embed_content(
            model=self.settings.gemini_embedding_model,
            contents=[
                (
                    "task: search result | query: "
                    if query
                    else "title: Kazhutha | text: "
                )
                + text
                for text in texts
            ],
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        return [embedding.values or [] for embedding in response.embeddings or []]

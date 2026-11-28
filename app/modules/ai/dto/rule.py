from dataclasses import dataclass

from app.modules.identity.schemas.profile import Language


@dataclass(frozen=True, slots=True)
class Rule:
    source: str
    terms: str
    en: str
    ml: str
    translations: dict[Language, str]

    def answer(self, language: Language) -> str:
        if language == "en":
            return self.en
        if language == "ml":
            return self.ml
        return self.translations[language]

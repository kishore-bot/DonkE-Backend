from xml.sax.saxutils import escape

from app.modules.ai.schemas.coaching import Situation
from app.modules.identity.schemas.profile import Language

MIN_SITUATION_DECISIONS = 5


def as_text(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


SITUATION_NAMES: dict[Language, dict[Situation, str]] = {
    "en": {
        "leading": "leading a trick",
        "following": "following suit",
        "cutting": "giving a Vettu",
        "near_escape": "the last two cards",
    },
    "ml": {
        "leading": "ആദ്യ ചീട്ട് ഇടുമ്പോൾ",
        "following": "അതേ ചിഹ്നം ഇടുമ്പോൾ",
        "cutting": "വെട്ടുമ്പോൾ",
        "near_escape": "അവസാന രണ്ട് ചീട്ടുകളിൽ",
    },
    "ta": {
        "leading": "முதல் அட்டை போடும்போது",
        "following": "அதே வகை போடும்போது",
        "cutting": "வெட்டும்போது",
        "near_escape": "கடைசி இரண்டு அட்டைகளில்",
    },
    "hi": {
        "leading": "पहला पत्ता चलते समय",
        "following": "वही रंग चलते समय",
        "cutting": "काटते समय",
        "near_escape": "आखिरी दो पत्तों में",
    },
    "kn": {
        "leading": "ಮೊದಲ ಎಲೆ ಆಡುವಾಗ",
        "following": "ಅದೇ ಬಣ್ಣ ಆಡುವಾಗ",
        "cutting": "ಕತ್ತರಿಸುವಾಗ",
        "near_escape": "ಕೊನೆಯ ಎರಡು ಎಲೆಗಳಲ್ಲಿ",
    },
    "te": {
        "leading": "మొదటి కార్డు వేసేటప్పుడు",
        "following": "అదే రకం వేసేటప్పుడు",
        "cutting": "కట్ చేసేటప్పుడు",
        "near_escape": "చివరి రెండు కార్డుల్లో",
    },
}


SUMMARY: dict[Language, str] = {
    "en": "Across {matches} matches your accuracy is {accuracy}%. You are strongest {strong}; practise {focus}.",
    "ml": "{matches} കളികളിൽ നിങ്ങളുടെ കൃത്യത {accuracy}% ആണ്. ഏറ്റവും മികച്ചത് {strong}; പരിശീലിക്കേണ്ടത് {focus}.",
    "ta": "{matches} ஆட்டங்களில் உங்கள் துல்லியம் {accuracy}%. நீங்கள் சிறந்தது {strong}; பயிற்சி செய்ய வேண்டியது {focus}.",
    "hi": "{matches} खेलों में आपकी सटीकता {accuracy}% है। आप सबसे अच्छे हैं {strong}; अभ्यास करें {focus}।",
    "kn": "{matches} ಆಟಗಳಲ್ಲಿ ನಿಮ್ಮ ನಿಖರತೆ {accuracy}%. ನೀವು ಅತ್ಯುತ್ತಮರು {strong}; ಅಭ್ಯಾಸ ಮಾಡಿ {focus}.",
    "te": "{matches} ఆటల్లో మీ ఖచ్చితత్వం {accuracy}%. మీరు బాగా ఆడేది {strong}; సాధన చేయండి {focus}.",
}


NOT_ENOUGH: dict[Language, str] = {
    "en": "Finish a few more matches to unlock your insights.",
    "ml": "നിങ്ങളുടെ വിശകലനം കാണാൻ കുറച്ച് കളികൾ കൂടി പൂർത്തിയാക്കൂ.",
    "ta": "உங்கள் பகுப்பாய்வைப் பார்க்க இன்னும் சில ஆட்டங்களை முடிக்கவும்.",
    "hi": "अपनी जानकारी देखने के लिए कुछ और खेल पूरे करें।",
    "kn": "ನಿಮ್ಮ ವಿಶ್ಲೇಷಣೆ ನೋಡಲು ಇನ್ನೂ ಕೆಲವು ಆಟಗಳನ್ನು ಮುಗಿಸಿ.",
    "te": "మీ విశ్లేషణ చూడటానికి మరికొన్ని ఆటలు పూర్తి చేయండి.",
}


ROASTS: dict[Language, str] = {
    "en": "{name} is today's Donkey! {cards} cards picked up from {cuts} Vettus. Better luck next deal!",
    "ml": "{name} ആണ് ഇന്നത്തെ കഴുത! {cuts} വെട്ടുകളിൽ നിന്ന് {cards} ചീട്ടുകൾ എടുത്തു. അടുത്ത കളിയിൽ ഭാഗ്യം വരട്ടെ!",
    "ta": "{name} தான் இன்றைய கழுதை! {cuts} வெட்டுகளில் {cards} அட்டைகள் எடுத்தார். அடுத்த முறை வாழ்த்துகள்!",
    "hi": "{name} आज का गधा है! {cuts} कटों में {cards} पत्ते उठाए। अगली बार शुभकामनाएँ!",
    "kn": "{name} ಇಂದಿನ ಕತ್ತೆ! {cuts} ಕತ್ತರಿಸುವಿಕೆಗಳಲ್ಲಿ {cards} ಎಲೆಗಳನ್ನು ಎತ್ತಿದರು. ಮುಂದಿನ ಬಾರಿ ಶುಭವಾಗಲಿ!",
    "te": "{name} ఈరోజు గాడిద! {cuts} కట్‌లలో {cards} కార్డులు తీసుకున్నారు. తదుపరి సారి శుభాకాంక్షలు!",
}


def wrap(text: str, width: int = 34) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + len(word) + 1 <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines[:6]


def card_svg(name: str, text: str) -> str:
    """A 1200x630 share card; every dynamic value is XML-escaped."""
    rows = "".join(
        f'<text x="600" y="{300 + 52 * index}" text-anchor="middle" '
        f'font-size="40" fill="#fff8e7">{escape(line)}</text>'
        for index, line in enumerate(wrap(text))
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" '
        'viewBox="0 0 1200 630">'
        '<rect width="1200" height="630" rx="36" fill="#1d3b2a"/>'
        '<rect x="24" y="24" width="1152" height="582" rx="28" fill="none" '
        'stroke="#e8b04b" stroke-width="6"/>'
        '<text x="600" y="120" text-anchor="middle" font-size="64" '
        'font-weight="700" fill="#e8b04b">KAZHUTHA</text>'
        f'<text x="600" y="210" text-anchor="middle" font-size="56" '
        f'fill="#ffffff">\U0001facf {escape(name)}</text>'
        f"{rows}</svg>"
    )

from app.modules.identity.schemas.profile import Language

TAUNTS: dict[Language, str] = {
    "en": "{name} here. You have beaten me {wins} times and lost {losses}. Round {next} is mine!",
    "ml": "ഞാൻ {name}. നീ എന്നെ {wins} തവണ തോൽപ്പിച്ചു, {losses} തവണ തോറ്റു. {next}-ാം റൗണ്ട് എന്റേതാണ്!",
    "ta": "நான் {name}. நீ என்னை {wins} முறை வென்றாய், {losses} முறை தோற்றாய். {next}-வது சுற்று என்னுடையது!",
    "hi": "मैं {name} हूँ। तुमने मुझे {wins} बार हराया और {losses} बार हारे। राउंड {next} मेरा है!",
    "kn": "ನಾನು {name}. ನೀನು ನನ್ನನ್ನು {wins} ಬಾರಿ ಸೋಲಿಸಿದೆ, {losses} ಬಾರಿ ಸೋತೆ. {next}ನೇ ಸುತ್ತು ನನ್ನದು!",
    "te": "నేను {name}. నువ్వు నన్ను {wins} సార్లు ఓడించావు, {losses} సార్లు ఓడిపోయావు. {next}వ రౌండ్ నాదే!",
}

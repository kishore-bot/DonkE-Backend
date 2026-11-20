from dataclasses import dataclass

from donke_engine import rank_passages


@dataclass(frozen=True, slots=True)
class Rule:
    source: str
    terms: str
    en: str
    ml: str


RULES = (
    Rule(
        "opening",
        "ace spades start opening lead first deal cards deck ഏസ് തുടക്കം",
        "The Ace of Spades opens the first trick. The whole 52-card deck is dealt.",
        "ആദ്യ കളി സ്പേഡിലെ ഏസ് കൊണ്ടുതന്നെ തുടങ്ങണം. 52 ചീട്ടുകളും വീതിക്കും.",
    ),
    Rule(
        "follow_suit",
        "follow suit matching hearts spades diamonds clubs lead ഒരേ ഇനം ചീട്ട്",
        "Play a card of the led suit if you have one. Otherwise you may play any card in your hand.",
        "ആദ്യം ഇട്ട ചീട്ടിന്റെ ഇനം കൈയിൽ ഉണ്ടെങ്കിൽ അതേ ഇനം ഇടണം. ഇല്ലെങ്കിൽ ഏതു ചീട്ടും ഇടാം.",
    ),
    Rule(
        "vettu",
        "cut vettu penalty pickup take pile highest off suit വെട്ട് എടുക്കുക",
        "A Vettu ends the trick immediately. The highest card of the led suit takes the entire pile and leads next.",
        "വെട്ടിയാൽ ആ കളി ഉടൻ തീരും. ആദ്യം ഇട്ട ഇനത്തിലെ ഏറ്റവും വലിയ ചീട്ടിട്ടയാൾ ചീട്ടുകൾ എടുത്ത് അടുത്ത കളി തുടങ്ങും.",
    ),
    Rule(
        "clean",
        "clean discard completed trick leader highest clear pile കളി",
        "When everyone follows suit, discard the trick. Its highest card leads next, or the lead passes if that seat has escaped.",
        "എല്ലാവരും ഒരേ ഇനം ഇട്ടാൽ ചീട്ടുകൾ മാറ്റിവയ്ക്കും. ഏറ്റവും വലിയ ചീട്ടിട്ടയാൾ അടുത്ത കളി തുടങ്ങും. ആൾ ഇറങ്ങിയെങ്കിൽ അടുത്തയാൾ തുടങ്ങും.",
    ),
    Rule(
        "escape",
        "escape safe finish empty hand donkey loss lose winner കഴുത ഇറങ്ങുക",
        "An empty hand is safe after the trick resolves. The last player still holding cards is the Donkey.",
        "കളി തീരുമ്പോൾ കൈയിൽ ചീട്ടില്ലാത്തയാൾ ഇറങ്ങും. അവസാനം കൈയിൽ ചീട്ടുള്ളയാളാണ് കഴുത.",
    ),
    Rule(
        "timeout",
        "timeout minutes seconds turn timer missed bot സമയം",
        "By default a turn lasts 40 seconds. A timed-out turn auto-plays a legal card.",
        "സാധാരണ ഒരു നീക്കത്തിന് 40 സെക്കൻഡ് കിട്ടും. സമയം കഴിഞ്ഞാൽ നിയമാനുസൃതമായ ഒരു ചീട്ട് സ്വയം ഇടും.",
    ),
)


def sources(query: str) -> list[Rule]:
    return [
        RULES[index]
        for index in rank_passages(query, [rule.terms for rule in RULES])[:3]
    ]

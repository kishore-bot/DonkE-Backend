# Offline evaluation scorecard

Run `uv run python -m scripts.evaluate --check` to reproduce this report. The fixtures cover curated rules, deterministic native deals, localized commentary facts and seasonal progression. Run `uv run python -m scripts.evaluate --trace` for the public data from a seeded story duel.

| Evaluation | Passed | Total |
| --- | ---: | ---: |
| Coach source selection and abstention | 12 | 12 |
| Strike commentary facts | 6 | 6 |
| Native game completion and card conservation | 16 | 16 |
| Awakening and grace period | 6 | 6 |
| English and Japanese scene fallbacks | 6 | 6 |
| Seeded story trace | 3 | 3 |

## Coach source selection and abstention

| Fixture | Expected | Actual |
| --- | --- | --- |
| Which card opens the first trick? | opening | opening |
| Do we deal the whole deck? | opening | opening |
| മലയാളത്തിൽ ഏസ് തുടക്കം? | opening | opening |
| Must I follow the led suit? | follow_suit | follow_suit |
| What is Vettu? | vettu | vettu |
| വെട്ട് എടുക്കുക? | vettu | vettu |
| What happens to a clean trick? | clean | clean |
| How do I escape with an empty hand? | escape | escape |
| അവസാനത്തെ കഴുത ആരാണ്? | escape | escape |
| How many seconds does a turn take? | timeout | timeout |
| What is the capital of Norway? | no match | no match |
| Recommend an avocado recipe | no match | no match |

## Strike commentary facts

| Fixture | Expected | Actual |
| --- | --- | --- |
| ml | vettu · 2, 4, 5 | vettu · 2, 4, 5 |
| ta | vettu · 2, 4, 5 | vettu · 2, 4, 5 |
| hi | vettu · 2, 4, 5 | vettu · 2, 4, 5 |
| kn | vettu · 2, 4, 5 | vettu · 2, 4, 5 |
| te | vettu · 2, 4, 5 | vettu · 2, 4, 5 |
| en | vettu · 2, 4, 5 | vettu · 2, 4, 5 |

## Native game completion and card conservation

| Fixture | Expected | Actual |
| --- | --- | --- |
| 2 seats, seed 119 | finished | finished |
| 2 seats, seed 2026 | finished | finished |
| 2 seats, seed 8128 | finished | finished |
| 2 seats, seed 65537 | finished | finished |
| 3 seats, seed 119 | finished | finished |
| 3 seats, seed 2026 | finished | finished |
| 3 seats, seed 8128 | finished | finished |
| 3 seats, seed 65537 | finished | finished |
| 4 seats, seed 119 | finished | finished |
| 4 seats, seed 2026 | finished | finished |
| 4 seats, seed 8128 | finished | finished |
| 4 seats, seed 65537 | finished | finished |
| 5 seats, seed 119 | finished | finished |
| 5 seats, seed 2026 | finished | finished |
| 5 seats, seed 8128 | finished | finished |
| 5 seats, seed 65537 | finished | finished |

## Awakening and grace period

| Fixture | Expected | Actual |
| --- | --- | --- |
| No choice during season | ready | ready |
| Needs points during season | ready | ready |
| Needs points at close | blocked | blocked |
| Claim at close | ready | ready |
| Claim on last grace day | ready | ready |
| Claim at grace deadline | blocked | blocked |

## English and Japanese scene fallbacks

| Fixture | Expected | Actual |
| --- | --- | --- |
| strike · en | valid | valid |
| strike · ja | valid | valid |
| victory · en | valid | valid |
| victory · ja | valid | valid |
| transform · en | valid | valid |
| transform · ja | valid | valid |

## Seeded story trace

| Fixture | Expected | Actual |
| --- | --- | --- |
| First clear | escaped | escaped |
| Public Strike call | landed | landed |
| Recorded rival evidence | rival-first-choice | rival-first-choice |

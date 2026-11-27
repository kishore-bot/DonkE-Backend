# DonkE mobile website plan

**Status:** Proposed for approval. Implementation will go in `C:\Users\kisho\Documents\projects\DonkE-Frontend`. Backend work will be a separate phase.

## Product direction

DonkE is a portrait-first anime-style website. Interviewers open a link and can immediately play Kazhutha against bots or watch a sample match. On desktop the same site presents a centered mobile layout. The first release needs one real animated 3D hero, an animated game table, and two switchable themes. The five launch screens are Home, Practice Setup, Table, Result, and Replay. Online play, Coach, Progress, Friends, and signed-in Profile can follow.

The supplied screenshots establish the visual direction. Use a large character stage, translucent panels, bold action buttons, a compact header, and strong theme accents. The supplied Expo prototype has a 12-screen layout, theme definitions, mock game data, and hard-coded sign-in and room states. I found no ready-to-use 3D asset bundle in it. The frontend destination folder exists and was empty when inspected. Use the prototype as a layout and interaction reference. Build the actual site in the frontend folder with original anime-style characters, insignia, move art, and narrator performances. The screenshot characters and emblems are visual references for composition and mood.

## Launch screens and data

| Screen | Layout and behavior | Data |
| --- | --- | --- |
| Home | Notice and theme control in the header, animated hero stage, prominent **Play vs bots**, then **Watch sample match**. Optional moment cards jump to a Vettu, escape, or finish in the sample. | `GET /api/v1/notice`, local theme, sanitized sample event bundle. Show real MMR only when a signed-in profile exists. |
| Practice Setup | Seat and difficulty controls, default **You + 3 bots · Medium**. The Home action can start directly with these defaults and offer setup via **Customize**. | `POST /api/v1/practice` with `seats` and `level`. Use returned game ID, practice token, private view, and events. |
| Table | Opponents and counts near the top, animated trick in the center, scrollable hand and Play at the bottom. Results of cuts appear as captions. A small audio button controls playback. | `GET /api/v1/practice/{id}`, `GET /hint` and `POST /plays` beneath that game path. Render returned legal cards and use expected version plus request UUID for each play. Retry the same command with the same UUID. |
| Result | Lead with the actual outcome and escape order. Actions are **Play again** and **Home**. | Final practice view and accumulated public events. Practice has no durable archived replay. |
| Replay | Reuse the table for playback. Add play/pause, previous/next, and a timeline with event markers. Use a labeled sample and include analysis only if a sanitized analysis export accompanies it. | Public sample bundle for launch. Signed-in replay and analysis later use `GET /api/v1/games/{id}/replay` and `/analysis` for participants. The sample contains no opening hands or tokens. |

Use a compact Home/Play navigation for launch and put the theme switcher in a header sheet available to guests. Add the prototype's Play, Coach, Progress, Friends, and Profile navigation as those destinations become functional. Terms such as **Vettu** and **Escape** stay understandable across themes. The fictional bounty, mana, rank, season, and MMR bonuses in the references have no corresponding data or mechanics and are excluded from the launch layout.

## Themes and real 3D

Start with two original palettes based on the supplied directions. **Crimson** uses red embers, slate glass, a ruined arena, and an original spellblade. **Tempest** uses navy, gold, a storm-lit deck, and an original sky corsair. Themes change color tokens, lighting, character, environment, effects, and narrators without changing the rules. Switching preserves the current game, selected card, pending request, replay position, and connection state. Persist only the theme preference in browser storage for launch.

- **Home stage:** Use a rigged, cel-shaded GLB character with breathing, weight shift, cloth or accessory movement, and an action clip. Place the character, floating A♠, environment, and particles at different depths. Limit touch interaction to the stage so vertical page scroll remains usable. Play actions stay available while the scene loads.
- **Game table:** Render the trick and card movement in a 3D scene. A card travels from its seat to the table on a confirmed play. A Vettu triggers a short impact followed by the pile moving to the receiver. Escape and finish have their own short motions. Keep the hand, buttons, turn status, and captions in accessible HTML above or alongside the canvas.
- **Replay and reconnect:** Feed animations from confirmed events. Fast-forward or skip effects during replay seeks and socket catch-up, then display the authoritative snapshot. Animation completion never gates commands, timers, or server state updates.
- **Mobile checks:** Lazy-load the selected theme assets and use one active canvas per screen. Pause offscreen or background rendering, cap render resolution, and lower particles and effects on slower hardware. Use reduced motion and a playable HTML/CSS table if WebGL is unavailable or loses context. Test the real rig and gameplay on iPhone Safari and Android Chrome before building out more scenes.

The 3D asset work includes a rig, animation clips, textures, and a mobile-friendly export for each hero. Build the first scene with an original model or an appropriately licensed rig, then validate it on phones before producing the second hero. See [React Three Fiber performance guidance](https://r3f.docs.pmnd.rs/advanced/scaling-performance).

## Frontend architecture

Use **React, TypeScript, Vite, React Router, CSS theme tokens, and React Three Fiber over Three.js/WebGL**. Host the built SPA as static files with route fallback. This is a browser-first project, with feature logic and API types structured for reuse if a native app is built later. Use feature modules with lightweight view models, meaning React hooks and reducers for screens with behavior. Keep simple screens as plain components.

- `app/` owns routing, the mobile shell, theme persistence, and app-wide providers.
- `features/` groups home, practice, match, replay, commentary, and future online or player features. A feature owns its UI and state transitions. Create separate hooks for table sessions and replay playback because each has a distinct lifecycle.
- `shared/api/` holds generated OpenAPI types, HTTP transport, error mapping, and adapters for practice and future multiplayer. Track socket sequence and command version separately when online play ships.
- `shared/scene/` owns scene loading, camera, animation clips, and effects. It consumes display state and confirmed events. It never determines legal moves.
- `themes/` maps theme IDs to design tokens, model URLs, effect presets, and narrator IDs. Keep separate caches for 3D assets and API state. Use component state for selections and a reducer for table transitions.

Deploy with same-origin HTTPS routing for the UI and API where practical. Configure explicit CORS if the origins differ. Browser multiplayer is a later phase because the current WebSocket requires a custom Bearer handshake header. Plan a short-lived, single-use socket ticket issued after HTTP authentication and bound to the player and match, or same-origin cookie authentication with origin checks. Keep credentials out of the frontend bundle and sample assets. See [Vite static deployment](https://vite.dev/guide/static-deploy.html), [browser WebSocket constructor](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/WebSocket), and the [current socket route](../app/modules/matches/router.py#L215).

## Backend changes for later

**Language assumption for approval:** The site UI stays English. There is no language picker in onboarding, Profile, or the match. **Crimson uses an English narrator and Tempest uses a Japanese narrator by default**, with captions matching each narrator. This treats language as part of the theme and keeps theme switching as the only selection. Audio starts muted until a user taps to enable it. If English captions over Japanese audio are preferred, decide that before implementing the response contract.

| Area | Proposed change |
| --- | --- |
| Commentary language | Add a dedicated `CommentaryLocale = en or ja` and an explicit theme-to-narrator mapping. Add reviewed Japanese lines and reactions for Vettu, escape, and finish. Render text from confirmed match events. Resolve the locale server-side from an allowlisted narrator ID, independently of the player's stored language. |
| API contract | Extend the existing match commentary and voice routes with a narrator ID and a documented default, or introduce versioned replacements if existing consumers need the old behavior. Return text with its language and narrator ID. Continue to distinguish WAV from pending, disabled, and failed JSON responses. Reject unknown narrator IDs and keep replay commentary participant-scoped. Update OpenAPI and fixtures. |
| Voice generation | Extend provider and queued job inputs to carry the resolved locale where useful for speech generation or pronunciation. Pass the exact localized transcript and use the same narrator for text and audio. Include locale, narrator, model, and script revision in cache identities. Keep queue leases, rate limits, quotas, and retry behavior. Make the commentary flag stop new commentary synthesis and define consistent behavior for cached clips. Check English and Japanese with the configured model and review Kazhutha terminology with a Japanese speaker. |
| Player preferences and migration | Remove language selection from the frontend immediately. The existing backend language enum also feeds coaching, personas, seed fixtures, and other features. Preserve existing stored values during rollout. Set English as the default for public UI and new accounts. Deprecate public language writes separately once consumers are accounted for. No database migration is needed for local theme persistence. Add a validated preference only if cross-device theme sync is later needed. |
| Guest demo | Existing dynamic commentary routes use player auth and online match state. Launch with bundled, original, pre-rendered English/Japanese clips and captions for a small set of practice and sample-replay events. Use generic lines where a clip cannot truthfully announce the exact seat or pile size. Live commentary on public practice would require a separately designed practice-token event lookup with quotas. |

The current locale coupling is visible in [profile schemas](../app/modules/identity/schemas.py), [commentary templates](../app/modules/ai/commentary.py), and [voice routes](../app/modules/ai/router.py). Google lists both target languages for the configured TTS model family. Provider output still needs a live test for both tracks. See [Gemini speech generation](https://ai.google.dev/gemini-api/docs/speech-generation#supported-languages).

## Delivery order and acceptance

1. **Prototype the experience.** Build the mobile shell, theme tokens, and one real rigged home scene in the frontend repository after approval. Verify touch scrolling, scene load, and performance on physical iOS and Android devices.
2. **Deliver the public demo.** Connect real practice create, snapshot, hint, and play. Add event-driven table animation, result, and sample replay. Add the second theme and bundled narrator tracks. Verify theme switching mid-game and playback in both themes. Publish an HTTPS preview after the hosting arrangement is agreed.
3. **Integrate backend changes.** Implement the two-narrator contract and validate actual WAV playback, locale rejection, caching, and the disabled state. Add browser-compatible auth before implementing live lobby, room, and game socket flows.
4. **Expand the signed-in site.** Add the remaining player screens from the prototype based on actual API responses.

The public demo is ready when a guest can open the URL, play a real move while the 3D table reacts, switch themes during a session, view a labeled sample replay, and hear the correct narrator after tapping audio. It must also remain playable with reduced motion or unavailable 3D and preserve the server's move ordering and retry behavior.

## Frontend implementation handoff

The first frontend pass uses the existing notice and practice APIs. It reserves model paths at `public/models/crimson.glb` and `public/models/tempest.glb`. The site can run with a procedural 3D scene while the project owner supplies rigged models. The owner will implement the backend changes separately.

| Pending backend interface | Frontend dependency |
| --- | --- |
| Browser WebSocket authentication | Keep the existing event and command shapes. Add a browser-compatible handshake before wiring live play. The current Bearer header works for native and smoke clients. |
| Theme narrator contract | Resolve Crimson to English and Tempest to Japanese, independent of profile language. Agree on a narrator field or parameter for commentary and voice. Until then the website omits network commentary and language selection. |
| Guest media and replay | Supply reviewed EN/JA clips or an eligible guest endpoint, and a sanitized public replay export for the sample route. |
| Hosted API origin | Route `/api` to DonkE at the same origin or configure explicit cross-origin support. Vite proxies local development requests. |

The current implementation contract is maintained separately in [Frontend backend changes](FRONTEND_BACKEND_CHANGES.md). For guest narration, the frontend uses matching device speech and captions while recorded audio is unavailable.

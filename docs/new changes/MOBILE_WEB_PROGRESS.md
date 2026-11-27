# DonkE mobile website progress

Updated 24 November 2026

**Current milestone:** The guest interview demo has passed a mobile browser smoke test locally. The Crimson model is integrated. Hosted delivery and end-to-end browser multiplayer are pending.

[Product and architecture plan](MOBILE_WEB_PLAN.md) · [Backend implementation handoff](FRONTEND_BACKEND_CHANGES.md)

## App idea

DonkE is a mobile browser game that brings **Kazhutha, Kerala’s card game**, to an animated anime-style table. The aim is to empty your hand before you become the Donkey. A Vettu, where an off-suit card ends the trick and sends the pile to another player, is the signature moment. The 3D table shows the cards moving so a first-time player can see what happened.

A guest can open the link, play a real match against bots, ask for a hint, or watch a sample replay. Crimson and Tempest change the scene, effects, and narrator. Crimson speaks English and Tempest speaks Japanese. Switching themes leaves the match in progress intact. The online experience extends this with private rooms, matchmaking, reconnect, and match replays.

**Interview pitch:** I built a backend for Kazhutha and gave it a playable mobile website. Rust owns the rules, FastAPI serves practice, and Redis and PostgreSQL support live matches and durable replays. You can play a card and see the server’s decision reflected on the animated table.

## 1. Build the mobile guest experience

- [x] Scaffold the React, TypeScript, and Vite site in the sibling `DonkE-Frontend` folder.
- [x] Build Home, Practice Setup, Game Table, Result, and Sample Replay.
- [x] Connect the notice and practice APIs for creation, snapshot, hints, and versioned plays.
- [x] Retain the request UUID for a retry of the same pending practice move.
- [x] Bundle a public-event-only sample from a seeded Rust game. Add playback, seeking, and jumps to Vettu, escape, and finish.
- [x] Add Crimson and Tempest theme switching. Persist the theme and keep the current practice session when switching.
- [x] Show English commentary in Crimson and Japanese commentary in Tempest. Play a matching device voice when available. Keep captions available and omit the language selector.

## 2. Integrate 3D and theme assets

- [x] Render 3D cards and animate confirmed plays and Vettu pile pickups. Provide a reduced-motion table.
- [x] Integrate the supplied Asta scene at `public/models/crimson.glb`. Animate the scene, floating card, and blade in code. The supplied pack has no skeletons or embedded animation clips.
- [x] Build a procedural animated scene for Tempest.
- [ ] Add the Tempest character scene when the asset is supplied. Place it at `public/models/tempest.glb`.
- [ ] Check character framing, performance, gesture behavior, and narration on physical iPhone and Android devices.

## 3. Finish browser multiplayer and server commentary

- [x] Build the Google sign-in, matchmaking, private room, ready, and invite flows against the existing HTTP API. Live sign-in still needs deployment configuration and verification.
- [x] Build the live table client with a reconnect cursor, authoritative snapshots, and resend of an unacknowledged move using the original UUID.
- [ ] Implement the browser WebSocket ticket endpoint and handshake in the backend. The frontend already expects this contract.
- [ ] Configure the Google web client ID on both sides and run a two-browser match. Verify room join, first sync, move acknowledgment, reconnect after a missed event, leave, and settlement.
- [ ] Implement the server-side Crimson and Tempest narrator contract. Wire the frontend to that API once it is available and verify actual English and Japanese WAV output.
- [ ] Add signed-in replay and analysis after the live match flow is verified.

## 4. Publish the interview demo

- [ ] Choose an HTTPS hosting target and configure routing from the website to the existing FastAPI service. The guest demo can ship before browser multiplayer and server-generated speech.
- [ ] Test the hosted URL in a fresh browser without sign-in. Start a practice game, request a hint, play a card, switch themes, and open the sample replay.
- [ ] Verify the deployed site on physical phones. If live multiplayer is included, verify WebSocket upgrades and the deployed Google sign-in flow.
- [ ] Save the public demo URL and a short interview walkthrough in the frontend README.

## Later expansion

- [ ] Build the full Coach, Progress, Friends, and Profile screens after the main match experience is stable. Keep the existing operator console as a separate interface.

## Verification completed

- The production frontend build passed after the Crimson GLB integration.
- A mobile-viewport Chromium smoke test loaded the Crimson GLB and exercised real practice, hints, move submission, theme switching, replay, Japanese captions, and reduced motion.
- The published URL, real-device rendering and audio, and end-to-end online multiplayer remain unverified.

**Next steps:** Publish and check the guest demo, implement the browser ticket contract for multiplayer, and add the Tempest asset when available.

# LivePulse UI Vision

**Status:** implementation-ready design direction for the post-M3 interface. This document specifies product behavior and architecture; it does not implement components or change backend contracts.

**Source baseline:** `PRODUCT_REQUIREMENTS.md`, `DEFINITION_OF_DONE.md`, `ARCHITECTURE.md`, `SECURITY_AND_PRIVACY.md`, and accepted ADRs 0001–0011. The verified `m3-verified` tag and `main` point to the current `codex/final-ui` base commit.

## 1. Design principles

1. **A workstation, not a dashboard.** Compose one continuous command surface around the current focus and the durable Pulse Timeline. Use planes, rules, alignment, and restrained material changes instead of a grid of generic cards.
2. **State earns emphasis.** A visible state comes from an authoritative projection, a normalized provider-health snapshot, a real canonical event, or a deterministic local Focus Timer. Never invent telemetry or imply a source is live because it is configured.
3. **Attention changes composition, not truth.** Focus may shift scale, contrast, depth, and information density inside reserved layout slots. It must not reorder the screen unpredictably or obscure persistent information.
4. **Keep history first-class.** The Timeline is an intelligence feed with chronology, source, freshness context, and durable history. It is not a dismissible notification pile.
5. **Quiet is a designed state.** A healthy idle system has a finished, legible composition and a calm Signal Field. No ambient animation is required to make the app feel alive.
6. **Separate connection from freshness.** `LIVE` currently means the browser WebSocket is connected. Provider freshness and local dependency health are separate facts and must have separate labels.
7. **One user, one machine.** PERSONAL_LOCAL stays loopback-only and single-user. PUBLIC_DEMO is visibly distinct, sanitized, and isolated. The UI must not imply login, remote private access, or multi-user guarantees.
8. **Desktop first, browser-safe.** Design for an always-open Windows second monitor at 1440×900, 1600×900, and 1920×1080. Browser fallback and smaller windows retain all information and controls without pretending to be a mobile product.
9. **Accessible by construction.** Motion, keyboard operation, contrast, focus, and semantic state are part of the architecture, not a later visual pass.

## 2. Screen anatomy

The default screen has four persistent zones and one contextual layer:

- **Instrument header, 56–64 px:** LivePulse identity at left; local weekday/date/time and concise weather context near center; runtime mode and System Pulse at right. Keep mode visible as `PERSONAL LOCAL` or `PUBLIC DEMO`, not buried in diagnostics.
- **Context line, 36–48 px:** current match mode or primary attention reason, selected competition/subject, and the last meaningful update. It is a compact orientation line, not a second page title.
- **Command workspace:** a 12-column grid. The primary focus/match stage spans 7 columns; the Pulse Timeline spans 5. The stage owns the most area and the Timeline stays visible beside it on target desktop widths.
- **Utility seam, 64–84 px:** Spotify Capsule and Focus Timer sit under the main stage as a compact shared instrument strip. They should not become independent large cards.
- **Quick-launch dock:** a nearly hidden lower-edge rail revealed by hover, keyboard focus, or the command palette. It overlays the workspace without reserving a permanent taskbar-like row.
- **Details layer:** System Pulse diagnostics, expanded timeline entries, device selection, and command palette open as anchored panels or a right-side sheet. They preserve the workspace underneath and close with Escape.

The visual signature is a **Pulse Field**: a low-profile (roughly 220–280×70–100 px) layered contour instrument embedded into the focus stage and echoed in miniature by System Pulse. It is a small, clipped field of 5–7 precise lines or elliptical planes, not a large central orb. In idle it is a composed static mark. In a match state it sits beside or just below the score/countdown; it never covers teams, score, or phase. Its geometry represents only known state channels: outer contour continuity for observed local health/realtime connection; aperture and spacing for Match Mode; inner height for the active server-owned focus band; a restrained edge accent for Spotify playing/paused/absent; and one temporary directional sweep for a real event arrival. It does not represent BPM, throughput, or any metric LivePulse does not have. Labels remain the source of truth.

## 3. Layout grid

- Use a centered content width of 1,600–1,720 px with 28–48 px side margins, 12 equal columns, and 20–24 px gutters. At 1440 px, target about 7/5 columns for focus and Timeline; at 1600 and 1920 px preserve the same relationship rather than stretching text indefinitely.
- Header content aligns to the same grid. Keep the clock, health, and mode instruments in fixed-width slots so status text changes do not shift the layout.
- The focus stage is a single continuous surface with three internal bands: competition/phase; teams and score or countdown; event/focus detail. Reserve the same geometry for idle, pre-match, live, halftime, and full-time states.
- The Timeline has its own vertical scroll region on desktop, with a visible newest-event marker and a separate older-history affordance. Preserve reading position when new events arrive.
- At 1366-ish widths, reduce gutters and stage padding first; keep Timeline at a readable minimum width near 380 px. Below roughly 1,180 px, stack stage and Timeline, make the Timeline height content-led, and avoid a hidden horizontal overflow state.
- At 900 px height, keep the header and primary match facts visible without scrolling. Let only the Timeline and expanded details panel scroll independently. Do not force a fixed full-screen layout where it would clip text scaling or keyboard focus.
- Avoid nested rounded-card grids. Primary surfaces use a quiet background plane and a fine edge; supporting instruments use open layout, dividers, and restrained inset surfaces.

## 4. Component hierarchy

Conceptual React hierarchy (names are design roles, not implementation files):

```text
LivePulseApplication
├── InstrumentHeader
│   ├── BrandMark
│   ├── AmbientClockWeather
│   ├── RuntimeModeLabel
│   └── SystemPulse
│       └── DiagnosticsPanel
├── CommandWorkspace
│   ├── FocusStage
│   │   ├── StageContext
│   │   ├── MatchCountdownOrLiveRing
│   │   ├── MatchScoreAndPhase
│   │   └── PulseField
│   ├── PulseTimeline
│   │   ├── TimelineChronology
│   │   ├── CanonicalEventRow
│   │   └── TimelineHistoryControl
│   └── UtilitySeam
│       ├── SpotifyCapsule
│       └── FocusTimerControl
├── QuickLaunchDock
└── CommandPalette
```

The data layer should separate four concerns: authoritative REST snapshots, incremental WebSocket events/cursors, provider snapshots/freshness, and deterministic presentation-only Focus Timer state. Views consume typed domain contracts. They do not make their own provider requests or re-derive server-owned attention priorities.

## 5. Visual hierarchy

1. Current high-priority subject or live match score.
2. Match phase/countdown and primary event detail.
3. Newest Pulse Timeline item and its source/time.
4. System Pulse state when anything is degraded, reconnecting, or resynchronizing.
5. Spotify, clock/weather, and active timer as persistent but secondary context.
6. Stable metadata, older history, and launch destinations.

High priority changes emphasis only within the first three levels. Critical alerts may interrupt; important mail and CI warnings remain noticeable in their reserved surfaces. A static numeric Focus score is diagnostic detail, not the hero. If shown, present it in an expanded focus detail with reason, source, subject, severity, and expiry.

## 6. Typography system

Use a practical Windows-native UI face with a licensable fallback. Preferred stack: `Segoe UI Variable`, then `Inter` if bundled under its SIL Open Font License, then `system-ui`. Use `Cascadia Code` or an OFL-licensed `IBM Plex Mono` for timestamps, scores, compact state values, and diagnostic codes. Do not bundle Microsoft fonts without distribution rights.

| Role | Target size | Treatment |
|---|---:|---|
| Focus display / match score | 48–72 px | Medium weight, tabular numerals, tight but readable spacing |
| Page/context heading | 24–32 px | Regular weight, short line length |
| Match countdown / primary clock | 28–40 px | Tabular numerals, high contrast |
| Surface and event title | 15–18 px | Medium weight |
| Body and event summary | 13–15 px | Regular weight, 1.4–1.55 line height |
| Metadata and source labels | 11–12 px | Mono or compact UI face; never below 10 px for meaningful status |
| Diagnostic codes / tertiary labels | 10–11 px | Muted but still readable; details panel only |

Use tabular figures for time, score, countdown, progress, and counts. Do not rely on all-caps letter-spaced 7–9 px text for primary status; current CSS uses it heavily and needs a readability pass.

## 7. Color and material system

Base the environment on graphite, not pure black: `#0B0F11` background; `#111719` primary plane; `#171E20` raised plane; `#20292B` separators; `#EDF1EE` primary text; `#BAC4BF` secondary text; `#83908A` muted text. Preserve visible focus outlines and minimum text contrast equivalent to WCAG AA for normal text.

Semantic color families:

- **Healthy:** muted sage, approximately `#91C7A5`.
- **Informational:** cool blue-gray, approximately `#8FB9C4`.
- **Active/live:** pale mint, approximately `#A8D7BE`.
- **Warning / rate-limited / stale:** controlled amber, approximately `#D7B36F`.
- **Critical:** restrained coral, approximately `#E28B7C`.
- **Degraded:** warm amber with a broken/segmented line treatment; use a text label as well.
- **Domain identity:** one small glyph or side marker per source (football, Spotify, GitHub, Gmail, weather). Keep the rest of each row neutral. Source identity must not create a rainbow surface.

Color never carries meaning alone: pair it with text, icon shape, or line continuity. Album artwork may create a blurred wash contained to the Spotify Capsule only, capped at about 3% opacity and removed when artwork is absent or stale. Weather can slightly alter a small edge light or surface tint; it cannot affect text contrast, global background brightness, or match colors. Use translucent material only for the header and anchored detail layers; provide opaque surface fallbacks when `backdrop-filter` is unsupported.

## 8. Depth and 3D rules

Use 2.5D as the default: layered planes, 1–3 px translation, controlled perspective on the Pulse Field, a soft edge highlight, and shallow blur at the edges of an anchored panel. No 3D navigation, spinning orb, parallax that follows cursor continuously, volumetric haze, refraction that distorts text, or bloom across the whole screen.

Depth has one job: make a real attention transition perceptible. Match Mode may bring the focus plane forward by at most a few pixels while peripheral context recedes slightly in contrast. It must not change grid dimensions or cause neighboring content to jump. The depth transition ends when the motion ends; persistent focus comes from scale, contrast, position within the reserved hero slot, and clear labels.

The P0 Pulse Field is CSS transforms plus inline SVG paths/shapes. Do not create a WebGL context in P0. A later measured experiment may replace only the decorative field with a small React Three Fiber canvas, feature-detected and capped to a compact area. DOM text, state, keyboard controls, and fallbacks remain complete without it.

## 9. Motion language

Motion encodes entry, change, and recovery. It does not run to decorate an idle screen.

| Motion token | Duration | Use |
|---|---:|---|
| `motion-tap` | 100–140 ms | Button/hover/focus response |
| `motion-micro` | 160–200 ms | Widget expand/collapse, dock reveal |
| `motion-standard` | 220–300 ms | Timeline insertion, track change, panel transition |
| `motion-state` | 320–440 ms | Match lifecycle and health-state composition change |
| `motion-spatial` | 440–560 ms | Match Mode enter/exit and full-time decompression |
| `motion-emphasis` | 650–900 ms | One critical event’s emphasis and release |

Use a shared ease-out curve for arrivals and an ease-in-out curve for state changes. Prefer opacity and transform. Animate height only for explicit expansion; avoid repeated layout measurement on every timeline update. New events use a short 6–10 px arrival and settle. Historical hydration has no entrance animation. A higher-severity event can interrupt a lower-severity transition; equal/lower events do not restart it. Never shake, flash, confetti, spawn random particles, or keep a glow pulsing indefinitely.

State-specific timing and decay are defined in `UI_STATE_MATRIX.md`. All durations collapse to immediate state changes under reduced motion. Reduced motion removes translation, scale, blur, and looped sweeps, but retains labels, icons, contrast, and static geometry changes.

## 10. Focus Engine visual behavior

Render the backend-owned focus decision; do not compute focus from timeline event types in React. The normalized decision controls emphasis through four visual bands: quiet, steady, elevated, and critical. The numeric score may smoothly interpolate a small amount of hero contrast/field height, but band changes set bounded size/contrast/depth states. A new score never changes the page grid.

Existing M2 semantics are authoritative today: idle 10, scheduled 40, live 70, halftime 52, full-time 30, goal 100 and red card 95 for a 12-second transient highlight. On expiry, refetch and settle back to the authoritative lifecycle state. The current engine is football-only. The requested Gmail (~85), CI failure (~80), and provider-degraded (~65) examples are target product policy, not current backend behavior. They require an explicit deterministic backend policy and a server-owned cross-domain focus contract before the UI can claim them. Do not create a client-side priority table as a shortcut.

The primary focus occupies a stable hero slot. A change of source crossfades the slot’s content and applies a restrained transform without moving the Timeline, header, or utility seam. Persistent match lifecycle remains visible even when another source temporarily wins focus. A transient critical event enters at full emphasis, receives one concise event cue, then decays exactly at the backend-supplied expiry. Focus Timer is a separate presentation mode: it quiets peripheral surfaces but never alters Focus Engine state or suppresses important events.

## 11. Match Mode states

- **PRE-MATCH / SCHEDULED:** competition, teams, kickoff in local time, and a compact countdown. Importance steps up as kickoff approaches; never infer that kickoff has happened because the countdown reached zero. Wait for an authoritative live state or show `KICKOFF DUE · WAITING FOR PROVIDER` with source freshness.
- **LIVE:** the match stage becomes the primary plane, score and phase are largest, and the live minute is clearly labelled. Timeline remains beside it. A live match is persistent elevated attention, not a repeated alarm.
- **HALFTIME:** preserve score and identity, label the break, lower ambient activity, and retain Match Mode. Do not look like a disconnected or finished match.
- **SECOND HALF:** return to the live arrangement with a concise phase transition cue; retain the same match identity and score.
- **FULL TIME:** show the final score and result as a resolved state. Give it a 450–560 ms decompression into the stable workspace, then preserve the final result until a new active/upcoming selection replaces it. Do not clear history or instantly collapse to empty.

The server remains authoritative for lifecycle and `match_mode`; the countdown is a local display derived from the fixture’s UTC `kickoff_at`. If the provider is stale or unavailable, freeze the lifecycle label and disclose freshness rather than inventing a transition.

## 12. Pulse Timeline design

The Timeline is an event chronicle with three scan layers: a narrow local-time rail; a domain/event marker with a severity form; and title, concise safe summary, source, and freshness context. Use full title and details on expand/hover, but keep the default row to two lines plus a visible source label. Do not hide chronology behind color or icons.

Events sort by occurrence time, then durable cursor for deterministic ties. Cursor remains a recovery watermark and is never shown as an event count. If `observed_at` differs materially from occurrence time, say `Observed 4m later`; otherwise show no redundant freshness text. Provider freshness lives primarily in System Pulse. The current timeline API has `timestamp` (occurrence), source, event type, payload, and cursor but does not expose `observed_at`; add that generic timestamp to the timeline presentation contract before promising late-arrival freshness details.

On live insertion, preserve scroll position. If the user is reading history below the newest row, show a small `N new signals` control rather than yanking the list to the top. The event stays in durable history even after an alert or local acknowledgement is dismissed. Expand/collapse reveals normalized event details only; never render raw provider DTOs, unfiltered payloads, credential values, full email bodies, or opaque identifiers as user-facing copy. Gmail remains metadata-only/read-only; its bounded subject/sender/snippet are shown only to the degree allowed by the backend projection. GitHub and other event links may be offered only from validated canonical URL fields.

Support cursor-based older-page retrieval using the API’s `before` cursor; initial rendering must not claim the first 80 items are the whole history. Do not add a separate provider-specific feed. Domain filters may be a compact Timeline toolbar later, but chronology stays unified by default.

## 13. The six selected widgets

1. **System Pulse:** compact always-visible header instrument described in section 14. Its trigger and expanded panel reveal diagnostics.
2. **Spotify Capsule:** 48–56 px artwork, track/artist, a restrained progress line, playback state, device name, and previous/play-pause/next controls when authorized and available. Use the existing playback snapshot and command contracts. Interpolate progress locally from `progress_ms`, `duration_ms`, and observation time; do not rerender the whole app each second. A command is explicit user intent. Disabled/unauthorized/rate-limited/no-device states remain labelled. Track art crossfades inside this capsule only.
3. **Match Countdown / Live Ring:** this is the main stage, not a separate tile. It morphs from the nearest selected upcoming fixture to the live score/phase using authoritative fixture and match data. The ring is a thin tick-mark arc with a legible countdown/phase label; no fabricated percentage progress.
4. **Ambient Clock + Weather:** compact header context with local weekday/date/time and configured weather condition/temperature. Weather data currently includes its own timezone/local time and Fahrenheit values; if that timezone differs from machine local time, label the weather timezone. Any weather ambience stays local to the header/background edge.
5. **Focus Timer:** one click starts 25, 50, or 90 minutes. Idle state shows three quiet duration actions. Active state shows remaining time, selected duration, and an explicit end action. It is deterministic UI behavior, independent of backend focus. It lowers non-text peripheral surface/decorative luminance by no more than 8%, preserves text contrast, removes nonessential motion, keeps Spotify controls usable, and allows critical match/health events through.
6. **Quick-launch dock:** four to six user-intent destinations, initially ChatGPT, GitHub, VS Code, Portfolio, and optional configured repositories. It reveals on hover, focus, or through the command palette; a labelled handle remains reachable by keyboard. It is a launch strip, never an imitation taskbar. Destination URLs/paths are explicit configuration, not guessed from machine state.

## 14. System Pulse behavior

System Pulse is the always-visible heartbeat instrument, not an overall green badge. Its compact state distinguishes (a) the browser’s realtime connection and recovery state, (b) locally observed infrastructure health, and (c) each provider’s configuration/freshness. Show `LIVE`, `RECONNECTING`, or `RESYNCING` for transport/recovery; show `DEGRADED` when local system evidence warrants it; show `DISCONNECTED` and `UNCONFIGURED` on the affected provider row. A disconnected optional provider is normal when not configured; stale, auth failure, provider failure, and rate-limited are not hidden. Infrastructure `status` must not be treated as a roll-up of provider health because the backend deliberately reports those channels separately.

The closed instrument shows the realtime state word plus one small Pulse Field contour: `LIVE`, `RECONNECTING`, `RESYNCING`, `DEGRADED`, or `CHECKING`. Provider rows use their own `DISCONNECTED`/`UNCONFIGURED` states. If infrastructure is healthy but one provider is stale, retain `SYSTEM HEALTHY · WEATHER STALE` (or equivalent), not a falsely all-green summary. For provider-first health, show concise counts only when backed by the provider map. Never use provider configuration alone to label a connection healthy.

Click/keyboard activation opens a diagnostics panel with sections for local components (PostgreSQL, Redpanda, outbox, projector, realtime) and providers (football, Spotify, GitHub, Gmail, weather). Each row shows normalized state, safe detail code translated to plain language, last success/observation age, and quota/cadence only where the health contract provides it. Do not show secret values, coordinates, raw exceptions, or payload data. While reconnecting, preserve last-known content with an explicit stale label until REST resynchronization completes.

## 15. Startup and state restoration

The shell appears immediately in a quiet `RESTORING LOCAL STATE` state. Fetch authoritative live state, recent timeline, runtime mode, system health, and configured widget snapshots concurrently. Show small per-surface placeholders only while their own request is pending; never block the screen behind a cinematic loader. As REST snapshots resolve, content settles in with one 160–240 ms opacity transition. Existing history does not animate in as new activity.

Open the WebSocket with the last durable cursor, then reconcile any replay/gap through REST according to ADR 0004. Mark connection as `RECONNECTING` or `RESYNCING` until the authoritative snapshot has been applied. A stale cached snapshot may be used as a visual placeholder only if it is explicitly labelled last known; it cannot be treated as current. Persist only non-sensitive UI preferences and the Focus Timer deadline. Resume a timer from its deadline and stop it if expired; never persist provider data, email content, or credentials in frontend storage.

## 16. ChatGPT external-launch UX

ChatGPT is a destination, not an integration. The launcher opens the user’s ordinary trusted ChatGPT experience externally (`https://chatgpt.com/`) through the Tauri shell opener when packaged and `window.open` with `noopener,noreferrer` in browser fallback. Do not embed it, call a ChatGPT API, pass LivePulse state, copy timeline content, or send credentials/context. Launch is a direct user action from the dock or command palette. The label may say `Open ChatGPT`; it must not look like an in-product chat control.

## 17. Interaction and keyboard model

- **Ctrl+K / Cmd+K:** open one command palette with deterministic local commands, navigation to existing LivePulse surfaces, Focus Timer choices, and launch destinations. Do not present unsupported natural-language queries as working AI.
- **Escape:** close the topmost layer first and return focus to its trigger; a second Escape may close the palette. It does not clear match or timer state.
- **Match stage:** a labelled expand/collapse action opens a larger match view; a palette action may invoke the same behavior. The user can always return to the stable workspace.
- **Focus Timer:** 25/50/90 minute buttons are directly reachable; avoid global single-key timer shortcuts. Timer state is changed only by explicit controls.
- **Timeline:** tab order follows chronology and controls. Arrow keys may move among rows only when the Timeline has focus; Enter/Space expands a row; Home/End moves to newest/oldest loaded row. Keep normal page scrolling available.
- **Dock:** every destination is a labelled button/link, not hover-only; hidden dock becomes visible on focus and via palette.
- **Hover/focus details:** hover can preview a tooltip, but clicks and keyboard activation expose the same information. Tooltips do not contain essential state.
- **Command behavior:** unknown free text is not sent anywhere and receives a clear local message that AI queries are not available in this milestone. Gmail remains read-only, Spotify commands remain bounded provider commands, and all state-changing controls explain the target before execution.

## 18. Responsive strategy

- **1440×900:** full 7/5 focus/Timeline split; 6–8 timeline entries visible; match and utility seam remain in first viewport.
- **1600×900:** same structure with modestly wider content; line lengths stay bounded.
- **1920×1080:** content max width prevents huge score/team gaps; do not add more columns just to fill the monitor.
- **1366-ish laptop:** compact header and spacing, but retain visible System Pulse, clock, match state, and Timeline. Timeline can become a shorter stacked region if width falls below the split threshold.
- **Smaller browser windows:** switch to one column in reading order: focus stage, Spotify/Focus Timer seam, Timeline, then dock/details. Condense text before hiding controls.
- **Mobile:** not P0. Maintain non-overflowing semantic order, usable controls, and readable Timeline rows, but do not spend the architecture budget on mobile-specific navigation.
- Browser fallback uses the same state contract and safe external-launch behavior. Tauri may add window chrome/close behavior later, but the web surface remains functional without native APIs.

## 19. Accessibility

- Honor `prefers-reduced-motion` on first render and throughout runtime; provide a settings override only if it does not contradict OS preference.
- All controls work by keyboard with a clear 2 px focus outline and no focus loss after panels close.
- Use semantic headings, buttons, links, lists, and status regions. Announce only meaningful state changes through a restrained `aria-live` region; do not announce every clock second or timer tick.
- Provide text labels for `LIVE`, `RECONNECTING`, `RESYNCING`, `DEGRADED`, provider states, match phase, and timer state. Never communicate solely through color, shape, animation, or a numeric score.
- Maintain WCAG AA contrast for body/important metadata, support 200% zoom/text scaling without clipping, and keep essential labels at 10 px or larger with 12–15 px body copy.
- Do not use hover as the only path to dock, widget detail, or timeline expansion. Respect `prefers-reduced-transparency` where available by switching to opaque materials.
- Screen-reader state for the Pulse Field is a concise sentence such as `System healthy; realtime live; Spotify connected and fresh`, not an SVG path description.

## 20. Performance budgets

- Target 60 fps during short transitions at 1440×900 and 1920×1080 on a representative Windows workstation; transitions must not delay WebSocket message handling or REST resync.
- Idle has no requestAnimationFrame loop, animated noise, or continuously moving particles. A one-second clock/countdown update is isolated to its widget; Spotify progress is interpolated without rerendering the root tree.
- Use CSS transform/opacity for the field and transitions. No WebGL canvas, custom shader, canvas timeline, or Web Audio in P0. If a measured P1 WebGL trial is approved, the DOM fallback must be equally legible, one small canvas only, capped DPR at 1.5, paused when hidden, and disposed on unmount/context loss.
- Keep the Pulse Timeline bounded to the page size, request older pages by cursor, and consider virtualization only after a benchmark shows need beyond a few hundred loaded rows. Live events should update one normalized store entry, not remount the whole workspace.
- Poll only snapshots with a documented freshness need. Respect existing provider cadence and rate limits; do not poll Spotify more often than its backend source contract. Pause decorative work when the window is hidden and refresh state on return.
- System health currently probes PostgreSQL and opens a Redpanda producer per `GET /system/health`; cache/coalesce the backend probe or use a visible-page 30-second steady cadence with faster recovery polling before shipping an all-day UI. Do not add aggressive health polling to simulate realtime.
- Reference-device targets: under 2% average idle CPU across a 60-second foreground sample, no growing heap over an 8-hour soak (allow bounded browser cache noise; no monotonic retained event growth), no more than one app-level frame of added latency for event presentation, and less than 100 MB incremental UI memory attributable to LivePulse rendering. Validate with browser/Tauri profiling; treat these as acceptance targets, not measured claims.

## 21. PUBLIC_DEMO behavior

Show a persistent `PUBLIC DEMO` environment label. Use only the isolated deterministic fictional simulator state. Render provider rows as `DISABLED IN PUBLIC DEMO` from the real health contract; do not show fake connected/fresh playback, weather, mail, repositories, or quota. Hide connection setup, OAuth, provider command, and private local data lifecycle actions. Never read or display personal provider identifiers, local paths, weather location, credentials, or historical data from PERSONAL_LOCAL. Keep the Pulse Timeline and Match Mode useful with sanitized demo events. The generic external ChatGPT destination may remain available because it sends no LivePulse context; label it as an external destination.

## 22. Explicit anti-patterns

- Generic SaaS/admin cards, KPI grids, fake charts, or Grafana-style health walls.
- Batman references/IP, Iron Man HUDs, sci-fi jargon, novelty fonts, cyberpunk neon, gamer RGB, giant glowing borders, central spinning orb, or fake “system metrics.”
- Confetti, random particles, constant scanning, endless pulsing, screen shake, audio cues, or animation on historical hydration.
- Dashboard-wide album color changes, unreadable metadata, information hidden only in hover, provider status inferred from credentials, or an overall `LIVE` badge that masks stale sources.
- Frontend-owned Focus priorities, client guesses about match kickoff/lifecycle, or hidden provider degradation.
- A persistent generic chat bar that implies AI is available, an embedded ChatGPT surface, or automatic context sharing with external ChatGPT.
- A Windows taskbar clone, guessed project paths, invented integrations, fake weather alerts, inferred unread/read state, Gmail mutations, or raw provider payloads.
- Reordering/resizing the page on every priority change or allowing one transient event to take over the whole screen for its full attention TTL.

## 23. Design tokens to implement

These are initial names and values for the future token layer; tune only through screenshot review and contrast checks.

```css
--color-canvas: #0B0F11;
--color-plane: #111719;
--color-plane-raised: #171E20;
--color-plane-inset: #0E1315;
--color-edge: #2A3436;
--color-edge-soft: #20292B;
--color-text: #EDF1EE;
--color-text-secondary: #BAC4BF;
--color-text-muted: #83908A;
--color-healthy: #91C7A5;
--color-info: #8FB9C4;
--color-live: #A8D7BE;
--color-warning: #D7B36F;
--color-critical: #E28B7C;
--font-ui: "Segoe UI Variable", "Inter", system-ui, sans-serif;
--font-data: "Cascadia Code", "IBM Plex Mono", ui-monospace, monospace;
--space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
--space-5: 24px; --space-6: 32px; --space-7: 48px;
--radius-control: 4px; --radius-plane: 8px;
--motion-tap: 120ms; --motion-micro: 180ms; --motion-standard: 260ms;
--motion-state: 380ms; --motion-spatial: 520ms; --motion-emphasis: 760ms;
--ease-arrive: cubic-bezier(.22,.61,.36,1);
--ease-state: cubic-bezier(.4,0,.2,1);
```

Keep depth/elevation and semantic state as token families too: `--plane-shadow`, `--focus-quiet`, `--focus-steady`, `--focus-elevated`, `--focus-critical`, `--health-healthy`, `--health-degraded`, and `--health-disconnected`. Use no provider-derived color as a global token.

## 24. Frontend technology recommendations

The current React 19, TypeScript, Vite, CSS, Lucide, and Framer Motion foundation is adequate. Prefer reducing state coupling and clarifying contracts over replacing the stack.

| Technology | Problem solved / proposed use | Cost and fallback | P0? |
|---|---|---|---|
| **Framer Motion** | Existing dependency; use for a small number of coordinated focus-stage transitions, score/event entry, and panel presence. | Bundle/runtime and layout-measurement cost. Prefer CSS for hover, color, progress, and simple fades; disable travel under reduced motion. | **Yes, restrained reuse.** Avoid broad `layout` animations. |
| **React Three Fiber / Three.js** | Could give the Pulse Field true shallow geometry if the CSS/SVG prototype cannot express a memorable mark. | Adds WebGL setup, context/lifecycle handling, bundle weight, GPU use, test burden, and long-open leak risk. Inline SVG/CSS is the fallback. | **No.** Evaluate only as an isolated P1 visual experiment after profiling. |
| **Custom shaders** | Fine control over refractive or contour materials. No current product problem requires it. | Highest shader/debug/context-loss/accessibility cost; fragile on integrated GPUs. CSS/SVG fallback. | **No; not recommended unless later evidence changes.** |
| **CSS filters/materials** | Limited blur at panel edges and a local album-art wash. | Backdrop blur can increase compositing work and may be unsupported. Use opaque planes and no blur as fallback. | **Yes, narrowly.** No text distortion or full-screen refraction. |
| **Web Audio** | No useful purpose: playback controls need Spotify’s playback contract, not an audio graph. | Adds permission/privacy/CPU expectations and does not provide trustworthy track state. | **No.** |
| **Canvas** | No P0 problem; SVG is more accessible for the compact state instrument and timeline. | Harder text/accessibility, DPR/GPU cost, and cleanup. DOM/SVG fallback. | **No.** |
| **CSS Grid / custom properties / SVG** | Stable spatial layout, semantic theme tokens, and crisp Pulse Field geometry. | Low complexity; supported by current stack. Use DOM layout if SVG rendering is unavailable. | **Yes.** |
| **Tauri shell opener (future)** | Opens ChatGPT and configured destinations in the normal external environment. | Requires a narrow platform adapter and explicit allowed URLs. Browser fallback uses safe `window.open`. | **Later packaging step, not P0 web dependency.** |

Real 3D is not part of the first implementation. The hero score, countdown ring, Timeline, widgets, and spatial transitions remain DOM/CSS/SVG. If an experiment is justified later, only the decorative Pulse Field uses 3D; its accessible state remains in the DOM.

## 25. Phased implementation order

1. **Contract and policy closure:** define global deterministic Focus behavior for Gmail/CI/provider health; keep Match Mode semantics separate; choose upcoming/live fixture selection and tie-breaks; expose generic timeline `observed_at`; type `runtime_mode`, provider freshness and widget DTOs. Record material backend policy changes in an ADR before UI work.
2. **Frontend state foundation:** split authoritative snapshots, realtime recovery, provider snapshot hooks, and the local Focus Timer store. Isolate one-second clock/countdown/progress updates. Add visible-page refresh and bounded health polling.
3. **Design system and shell:** implement tokens, header, 12-column layout, stable stage slots, reduced-motion modes, focus/keyboard semantics, and explicit PERSONAL_LOCAL/PUBLIC_DEMO identity.
4. **Focus stage and Timeline:** implement idle, pre-match, live, halftime, second-half, goal/red-card transient, and full-time states; add cursor history and safe canonical event presentation. Verify reconnect/resync and stale-state labels.
5. **Six selected widgets:** System Pulse diagnostics; Spotify playback capsule/controls; clock/weather context; Focus Timer; Match Countdown/Live Ring; Quick-launch dock with external ChatGPT.
6. **Spatial motion and attention tuning:** add state transitions using shared motion tokens, test Focus Timer quieting, ensure important match/health events still surface, and validate reduced-motion behavior.
7. **Runtime and long-open verification:** test PUBLIC_DEMO isolation, 1440×900/1600×900/1920×1080/1366 widths, keyboard-only use, contrast/text scaling, reconnect loops, and an 8-hour soak. Profile idle CPU, heap, and WebSocket/event latency before considering any WebGL work.

## Current architecture refactors and open decisions

The present frontend has a sound M2 foundation but should not be expanded by adding more unrelated cards. Before implementation, address these concrete gaps:

- `App.tsx` updates its root state every second for the clock, causing the workspace and Timeline to rerender. Isolate time/countdown/progress widgets.
- `useLivePulse` mixes REST snapshots, WebSocket recovery, timeline ordering, and demo controls. Separate these state boundaries while preserving ADR 0004’s snapshot authority, durable cursor, dedupe, and resync behavior.
- `useSystemHealth` polls every 15 seconds; each backend health request probes PostgreSQL and creates a Redpanda producer. Add probe caching/coalescing or another measured visible-page cadence before polling it all day.
- `SystemHealthPanel` lists infrastructure components only. It does not render the `providers` map or `runtime_mode`; `types/livepulse.ts` does not type those fields. System Pulse requires a complete normalized typed health contract without treating optional-provider disconnects as system failure.
- `ConnectionBadge` labels the WebSocket as `LIVE`, which can be misread as all providers live. Retain transport truth but label it `REALTIME LIVE` alongside provider freshness.
- `FocusState` and `MatchSurface` are currently match-centric. Cross-domain priorities in the prompt are not implemented. Add a deterministic backend-owned global focus decision and keep match lifecycle/Match Mode independently truthful before exposing Gmail/CI/provider attention.
- Frontend data clients/types do not include football fixtures, Spotify playback/devices, weather, or provider freshness despite backend endpoints existing. Add typed contracts and explicit loading/stale states; do not pass vendor DTOs through.
- The Timeline frontend fetches one 80-item snapshot and caps live items at 100; it has no older-page action and its response lacks `observed_at`. Add cursor pagination and freshness semantics before calling the feed complete.
- Generic event fallback text can expose `subject_id`; replace it with canonical event presentation and safe summary rules. Keep Gmail metadata bounded and read-only.
- The command surface is always visible and says “Ask anything” despite only implementing a short local command registry. Replace it with the explicitly local command palette and the separate destination dock.
- `LOCAL DEMO STACK` is hardcoded in the current rail and frontend health typing omits the mode, so PUBLIC_DEMO cannot be represented correctly. Use the real health `runtime_mode` and the explicit demo provider status.

Decisions to close before visual implementation: (1) policy/tie-break order when more than one match is live or upcoming; (2) exact cross-domain Focus scores and expiry/acknowledgement behavior for important Gmail and CI failures; (3) whether VS Code/repository destinations are user-configured in P0 or only the four named defaults; and (4) whether a 3D Pulse Field experiment earns its GPU/bundle cost. Recommended defaults are nearest kickoff with stable competition/id tie-break, server-owned transient mail/CI policy with timeline permanence, user-configured destinations, and no P0 WebGL.

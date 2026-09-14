# LivePulse UI Vision

**Status:** final React UI implementation for a real `PERSONAL_LOCAL` LivePulse runtime. A local desktop application is the delivery target; the browser remains the development and fallback shell until a later Tauri v2 packaging milestone. The UI is prepared through a narrow platform adapter; Tauri, Rust, sidecar lifecycle, packaging, and native capabilities are not implemented here.

## Visual source of truth

The locked reference images are authoritative for composition and material treatment:

- Landscape: [`docs/ui-reference/livepulse-landscape-locked.png`](ui-reference/livepulse-landscape-locked.png)
- Portrait: [`docs/ui-reference/livepulse-portrait-locked.png`](ui-reference/livepulse-portrait-locked.png)

When prose in older UI documents differs, these images win. Reproduce their NYC night skyline, graphite/navy panels, cyan/teal accents, stadium hero, dedicated Gmail panel, Recent Signals, Spotify rail, Quick Launch, and compact status strip. Keep domain truth, accessibility, and stable responsive behavior intact while matching the visual proportions. Do not put PUBLIC_DEMO or deterministic fixture presentation into the production UI.

## Design principles

1. **One environment, multiple instruments.** The page is composed as a single personal operations workstation rather than a set of equal dashboard cards. The match, Gmail, timeline, system health, Spotify, and launch controls have clear spatial relationships and share an environmental layer.
2. **The references set the composition.** Retain the NYC/stadium cinematic treatment, glowing city windows, measured cyan highlights, luminous score, and translucent matte surfaces. Do not return to a sparse terminal or generic SaaS grid.
3. **Truth controls emphasis.** Live data comes from authoritative projections, provider snapshots, canonical Timeline events, health observations, and the local Focus Timer. A configured provider is not necessarily connected or fresh. The UI never invents scores, inbox rows, playback, weather, or telemetry.
4. **Football is the hero.** The dominant stage contains the selected fixture and owns live/upcoming/recent browsing, match details, and multiple-game switching. There is no separate “Next Up” surface.
5. **Gmail replaces the former side widget.** The read-only inbox occupies a dedicated, narrower rail beside the football hero, with Focus controls beneath it in landscape. Message bodies are not fetched for the dashboard.
6. **The Timeline is shared history.** It combines provider domains with chronology, readable event summaries, source identity, and older-history access. Reconnect/replay does not replay live arrival motion.
7. **Quiet states are complete.** Unconfigured or unavailable providers keep their geometry, say what is missing, and leave other surfaces usable. Idle has no perpetual animation.
8. **Keep the React shell portable.** UI code calls a platform service for external launch, authorization entry, API/realtime URLs, fullscreen, and future in-app route adaptation. Native APIs do not enter components.

## Landscape anatomy

At 1920×1080 and 1600×900, use a slim fixed left navigation rail and a workspace filling the remaining window. At 1440×900 and 1366×768, tighten padding and panel density before reducing type size; permit vertical scrolling if the available height cannot contain the minimum readable stage.

The top environment bar aligns LivePulse identity and “Your world, in signal.” with local time/date, provider-backed weather, System Pulse, provider mini-state, and a browser fullscreen control. The headline/context line remains short and carries useful state such as current dominant signal, focus session, or realtime status. It never contains quotes or decorative slogans.

The main row has three spatial columns. Allocate approximately 58% to the football hero, 21% to a Gmail/Focus rail, and 21% to Recent Signals, with readable minimum widths and consistent gutters. Gmail uses the upper part of its rail; a compact Focus Timer sits directly below it. The lower rail uses approximately 65% for Spotify and 35% for Quick Launch. A narrow footer exposes local mode and realtime truth. The page must not create horizontal overflow at supported landscape sizes.

## Portrait anatomy

At 1080×1920, retain the left navigation as a slim vertical rail. The top rows contain branding, clock/date, weather, and System Pulse. The football stage spans the workspace width and stays dominant. Gmail and Recent Signals occupy equal, readable columns below it. Spotify uses the full width, followed by the full-width Quick Launch strip and compact footer. Focus remains one action away in navigation; an active session is identified in the context line. This is a portrait-specific composition, not a scaled or mechanically stacked landscape grid.

Switching orientation only changes CSS composition. It must not remount provider hooks, recreate the WebSocket, restart Focus, reset match selection, or restart Spotify progress. Use orientation media queries and shared React state, not separate apps.

## Layout and hierarchy

- Preserve the left rail and fixed workspace alignment. Recommended landscape grid: `minmax(500px, 1.72fr) minmax(270px, .62fr) minmax(270px, .60fr)` for the hero, Gmail/Focus rail, and Timeline; rebalance with the same hierarchy at smaller widths.
- Keep Spotify and Quick Launch in a two-column lower rail. The intentional launch destinations remain visible, matching the locked references; they are a compact LivePulse surface, not a Windows/macOS taskbar clone. Unconfigured Portfolio/Strata entries open Settings instead of pretending to launch.
- Reserve the same hero geometry across idle, scheduled, live, halftime, and full-time. Score and teams must not cause the page grid to jump.
- Keep Timeline content independently scrollable when it has substantial history. Preserve the reading position when live items arrive and cap rendered history; older entries load by cursor.
- Below approximately 1180 px in landscape, use a compact two-column workspace with football occupying the tall left span and Gmail/Timeline on the right. Below tablet width, use a single-column flow with no hidden horizontal scroll.
- Portrait middle rail stays Gmail plus Timeline side-by-side. Focus controls are available on the Focus page and through the command palette.

The strongest hierarchy is: live/important football state; score or countdown; current match identity; Gmail and Recent Signals; Spotify; Focus and Quick Launch; ambient clock/weather. System Pulse remains visible in every posture. Color and movement reinforce explicit words/icons; neither carries state alone.

## Visual system

### Typography

Use practical system sans-serif faces (`Segoe UI Variable`, `Segoe UI`, then sans-serif) for readable product text, with a restrained system monospace stack for time, score metadata, provider states, and Timeline timestamps. Use tabular numerals for clock, countdown, score, and playback progress. Display text is large and light, not novelty sci-fi. Metadata is compact but must stay legible at 1440×900; do not solve density with microtype.

### Color and materials

The environment uses deep navy, graphite, and near-black. Primary text is high-contrast cool white; secondary text is desaturated blue-gray. Cyan/teal means active realtime or football state, soft sage means confirmed healthy, amber means warning/reconnect, coral means critical, and provider identity appears only as a small local cue. A missing optional provider is neutral, not a system alarm. Keep album-art ambience clipped to Spotify.

Glass is restrained: dark translucent planes, thin low-contrast edges, local backdrop blur, subtle inset highlights, and soft material shadows. Prefer a readable opaque fallback where blur is unavailable or expensive. Do not add luminous borders to every surface or rain/snow particles over content.

### NYC environment and depth

Use the bundled NYC skyline family, not remote image URLs. Select landscape or portrait crop from orientation. Local time chooses dawn/day/dusk/night treatment; real weather, when configured and fresh, may gently grade sky brightness, color temperature, and horizon atmosphere. Crossfade variants/tone over roughly 1–1.5 seconds. Without weather, use the local-time treatment and an explicit unavailable/not-configured label.

The skyline is a distant plane behind the UI; stadium imagery stays inside the football hero. Use soft atmospheric gradients and vignette to establish depth without obscuring city identity. Match Mode can move the hero forward a few pixels and recede supporting planes within reserved geometry. Focus quiets peripheral saturation and movement while retaining contrast. No parallax is required for pointer motion.

The Pulse Field is a low-profile SVG contour instrument embedded in the match stage. Its curves reflect only real categories (connection, match posture, server focus band, Spotify activity, event arrival). The DOM retains labels and source truth. CSS/SVG is the P0 renderer; Three.js, React Three Fiber, custom shaders, Canvas, and Web Audio are not justified for this compact signature.

## Component and data hierarchy

`App` owns navigation, shared snapshots, transient presentation state, and the single realtime hook. `Platform` owns shell boundaries. Feature components consume typed hooks/contracts and never construct provider hosts directly.

- **Environment:** `AmbientHeader`, `SpatialEnvironment`, `SystemPulse`.
- **Football:** `MatchStage`, selected-match state, Pulse Field, and the match detail surface for updates, schedule/recent fixture selection, lineups, and stats.
- **Signals:** `PulseTimeline` with durable cursor history and domain-aware presentation.
- **Gmail:** read-only list and on-demand safe metadata detail.
- **Music:** `SpotifyCapsule` with provider-confirmed commands, timestamp-based local progress interpolation, and device handling.
- **Focus:** persistent local deterministic timer with 25/50/90 presets, pause/resume/end, and a context-line active indicator.
- **Navigation:** `QuickLaunch`, local command palette, and destination settings.

Data lifecycle stays separated: REST snapshots are authoritative; WebSocket messages are notifications/replay; visible provider surfaces poll on bounded intervals and pause while hidden; local Focus state persists separately. Components do not probe providers just to render.

## Football and Match Mode

Select the default match by provider-backed live relevant match, then deterministic server focus, then nearest upcoming fixture. A manual selection is stable while the user is browsing; pin holds it temporarily, and Auto returns to provider selection. Previous/next controls and keyboard navigation are available when the football hero has focus.

The hero shows real competition, team names/crests where supplied, kickoff or score/minute, phase, meaningful recent events, and a consistent lower tab strip. Tabs only show supported data. Unsupported lineups or statistics use a concise truthful empty state, never invented formations/stats. Schedule/recent fixtures and “View Match” live in an overlay or drilldown over the same composition.

Upcoming importance may rise at defined windows, but countdown zero remains “kick-off due; awaiting provider” until the provider changes lifecycle. At kickoff, the stage establishes Match Mode inside the existing footprint. Goals emphasize the changed score and scoring side once, insert the canonical Timeline item, respond with a local field/light cue, then settle. Red cards use a sharper, distinct localized cue. Halftime is calm and explicit; full time briefly resolves the result then releases Match Mode. No confetti, sound, flashing, or whole-screen shake.

## Gmail and Pulse Timeline

Gmail displays about four curated real metadata rows in landscape and a smaller readable number in narrow layouts. Prefer unread/important/recent ordering from the backend service. Rows show sender, subject, bounded safe snippet, received time, unread/important mark, and a stable initial/avatar treatment. View all expands to the bounded list; clicking opens a read-only metadata dialog. “Open Gmail” launches externally through `openExternal`. No body persistence, send, reply, archive, delete, mark-read, or labels.

The Timeline mixes football, Spotify, Gmail, GitHub, weather, and system events. Each row shows a domain cue, plain-language title, safe secondary detail, occurred time, and source/observed freshness when available. Canonical event identity deduplicates insertion; occurrence and observation timestamps remain distinct. A replayed/resynced event enters history without a new-event animation. Empty history tells the truth while preserving panel geometry.

## System Pulse and provider truth

System Pulse remains a compact header instrument with connection word, backend request state, provider glyphs, and an expandable diagnostics panel. Connection states are `CONNECTING`, `LIVE`, `RECONNECTING`, `RESYNCING`, and `DEGRADED`; backend states are starting, ready, and unavailable; provider states remain independent (healthy, stale, degraded/rate-limited/auth-failure, unavailable, disconnected, unconfigured). Showing `LIVE` means the WebSocket is open, not that all providers are fresh. Opening diagnostics reads current state only and does not trigger probes.

The browser must remain composed while the backend starts, becomes unavailable, reconnects, or resynchronizes. Last-known domain content remains labelled as last-known/stale where supported. Realtime recovery reconciles REST state and cursor history without presenting replay as a new event.

## Spotify, Focus, and launch

Spotify includes trusted art, title/artist/context, elapsed/duration/progress, playback state, device, and supported previous/play-pause/next/device-transfer controls. A command shows pending state and reports failure; it does not optimistically claim success. Progress interpolates locally from provider timestamps; playback is not refetched every second. Track transitions are clipped to the capsule and reduced under Focus/reduced-motion settings.

The Focus Timer is a deterministic UI session, not the server Focus Engine. Start 25/50/90 minutes, pause/resume, stop, persist the deadline/remaining time locally, restore across refresh, and complete cleanly. Focus quiets peripheral motion and saturation without dimming text or suppressing football/system alerts.

Quick Launch contains LivePulse Home, ChatGPT, GitHub, VS Code, Portfolio, and Strata as in the reference. ChatGPT opens the normal trusted external experience; there is no ChatGPT API or embedded chat. VS Code and user destinations are configurable. An unconfigured Portfolio/Strata action routes to destination Settings. The palette is local and deterministic: Ctrl/Cmd+K opens it; arrows move, Enter runs, Escape closes; commands include navigation, Gmail, current/next/previous match, health, focus presets, launches, and setup routes. There are no browser tabs/popups for internal navigation.

## Motion, startup, and accessibility

Use one timing family: tap 120 ms, micro 180 ms, standard 260 ms, state 380 ms, spatial 520 ms, event emphasis 760 ms, with weighted settle easing. Tooltips and hover remain micro; startup and Match Mode establish with state weight; goals/red cards receive one local transient response. Track changes crossfade art/metadata; provider degradation is a clear static transition; reconnect/resync has one entry cue, not a continuous spinner. Focus start/end reduces peripheral motion. Orientation changes do not replay startup.

The wake sequence immediately renders useful structure and real current request state. Brand/environment establish first, then top instruments and panels settle over about 1.8–2.4 seconds under normal local conditions. It never blocks interaction or waits artificially for optional providers; reduced motion uses immediate/opacity-only establishment. OAuth return and browser refresh restore the app without replaying the wake sequence as a full cinematic.

Use semantic buttons and links, labeled dialogs and live status, keyboard navigation, visible focus, Escape dismissal, and reduced-motion styles from initial render. Ensure contrast on the skyline and images; state must include text/icon/shape, not color alone. Keep the clock isolated from app-wide renders.

## Platform boundary and later desktop packaging

`web/src/lib/platform.ts` is the only React-facing shell boundary. Components use:

- `isDesktopShell()` for nonvisual capability decisions only.
- `openExternal(url)` / `launchExternal(target)` for external sites or apps.
- `beginAuthorization(path)` for provider authorization entry/return handling.
- `requestFullscreen()` for browser fullscreen with a future shell implementation hook.
- `apiUrl(path)`, `websocketUrl(path)`, and `connectRealtime(path)` for centralized backend transport.
- `navigateWithinApp(path)` as the future adapter seam for the single-window application.
- `getPreference(key)`, `setPreference(key, value)`, and `removePreference(key)` for durable local UI preferences.
- `getBackendLifecycle()` and `subscribeBackendLifecycle(listener)` for shell-owned backend startup/readiness/shutdown observations.

The browser implementation may use `window.open` for intentional external launches, `location` for OAuth navigation, browser Fullscreen API, env-specified API/WebSocket bases, localStorage for Focus Timer, selected match, and user-configured launch targets, and sessionStorage for the wake-once policy. These browser-only behaviors are isolated in the platform service; the Vite development fixture selector also uses a query parameter but is excluded from production. Product navigation is in-window React state; browser tabs and popups are only for intentional external destinations. A later Tauri pass must replace external opening, OAuth return navigation, fullscreen, runtime endpoint configuration, and browser preference/wake storage through an injected adapter. The shell will own sidecar startup/readiness/shutdown, monitor placement, remembered window position/size, native capabilities, and packaging without importing native APIs into feature components. Preferred-monitor behavior is a shell responsibility and has no frontend setting in this milestone. No Tauri-specific Rust, plugin, capability, or shell config belongs to this UI milestone.

The API and WebSocket have same-origin Vite proxy defaults for browser development; configured `VITE_API_BASE_URL`, `VITE_WEBSOCKET_BASE_URL`, or adapter values select the local backend endpoint. A desktop adapter must provide the local API and WebSocket endpoints (or a deliberately configured build endpoint); the transport fails closed rather than targeting the WebView origin by accident. Do not duplicate localhost hosts across components. `PERSONAL_LOCAL` remains loopback-only except for its exact configured GitHub webhook POST host/path exception; browser and WebSocket boundaries remain local. A later shell must use only an allowed local origin or a deliberate shell transport/auth design; never broaden the trusted-origin allowlist to hide a failed upgrade. The browser health probe shows `starting` during a bounded startup grace, then `unavailable` with bounded retries; a desktop host can provide an immediate lifecycle snapshot and startup/shutdown changes through the adapter. If that host says `ready` but the health endpoint cannot be reached, the UI shows `unavailable`; REST health and realtime remain independently observed.

## Performance and resource budgets

- Avoid WebGL/canvas loops and any always-running animation. At idle, CSS transitions are dormant; the clock ticks locally once per second; countdown/progress derive from existing timestamps.
- Keep one WebSocket per mounted app, close it on teardown, bound reconnect/backoff, Timeline render/history, provider caches, and timers. Do not poll while hidden.
- Target 60 fps for short transitions on a mainstream integrated GPU; avoid animated full-screen blur and continuous parallax. A non-blurred material fallback must remain legible.
- Keep production frontend initial JavaScript under 500 KiB minified (currently approximately 433 KiB before future splitting) and avoid adding a 3D engine without measured benefit.
- On a four-hour foreground soak, provider/network cadence must remain contract-bounded, timer count stable, memory trend flat after warm-up, and idle UI CPU near zero aside from the local clock and realtime heartbeat.

## Public demo and explicit anti-patterns

PUBLIC_DEMO backend isolation remains a security concern, but it has no production UI label, demo presentation, fixtures, controls, or visual state. Visual fixtures are dynamically imported only in Vite development and are absent from production chunks.

Do not add: generic equal-card dashboards; a standalone Next Up panel; fake fixtures/inbox/playback/weather/telemetry; quotes, calendars, meetings, news, stocks, or unrelated widgets; a Windows/macOS taskbar clone; embedded ChatGPT or AI controls; rainbow panels, neon borders everywhere, cyberpunk/RGB styling, HUD clichés, particle storms, confetti, fullscreen flash/shake, automatic popups, browser-extension dependencies, or native/Tauri imports in UI components.

## Implementation order and status

1. Preserve authoritative provider/event/focus contracts and close exact local HTTP/WebSocket security boundaries.
2. Establish the shared responsive shell and injected browser platform service.
3. Reproduce the locked skyline, football/Gmail/Timeline hierarchy, lower Spotify/Quick Launch rail, and distinct portrait composition.
4. Connect real provider states, safe Gmail metadata, football schedule/details, Spotify commands, System Pulse, and Focus behavior.
5. Complete deterministic commands, keyboard/accessibility, startup, event motion, and error/recovery states.
6. Validate production excludes fixture UI; inspect all locked landscape/portrait and sanity resolutions; run integration/recovery checks and update Definition of Done.

The React UI is designed to run as one window with no dependency on browser tabs, extensions, or address-bar navigation for internal workflows. Browser fallbacks exist only for development and ordinary external destinations. Provider credentials and live external-provider accounts remain operator-dependent verification conditions; the shell adapter and local fallback states do not require them.

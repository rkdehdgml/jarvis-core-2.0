# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

jarvis-core is a Windows-native Korean-language personal AI assistant ("자비스"/J.A.R.V.I.S). The AI fallback
engine is pluggable (`core/engines/`): `claude_code.py` shells out to the **Claude Code CLI** (`claude -p ...`),
`groq_engine.py` calls the **Groq Python SDK** directly (`llama-3.3-70b-versatile`, API key via `.env`). Exactly
one is wired up at a time via a single import line in `skills/skill_ai_chat.py` (`from core.engines.<x> import
<X>Engine as Engine`) — check that line to see which is currently active. There is no direct Anthropic API call
anywhere in this codebase regardless of which engine is active. Voice input/output is optional; everything also
works in a text-only mode.

The full design rationale and step-by-step build plan live in `JARVIS_PLUGIN_DESIGN.md`. Read it if you need
the "why" behind a structural decision — this file only covers the "what" and "how".

## Commands

```powershell
# Setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run (voice mode: wakeword "자비스" → STT → route/dispatch → TTS)
python main.py

# Run (text-only mode, no mic — also the debug/fallback path)
python main.py --text

# Run the web dashboard (separate process, separate port)
uvicorn ui.server:app --host 127.0.0.1 --port 8765

# Frontend (ui/web — React + TS + Vite)
cd ui/web
npm install
npm run dev         # Vite dev server, http://localhost:5173
npm run build       # tsc -b && vite build
npm run typecheck   # tsc --noEmit

# Tests (no pytest — plain assert-based scripts run as modules)
python -m tests.test_skills_step5
```

There is no linter/formatter configured. There is no `pytest`; tests are standalone scripts under `tests/`
that `assert` and print results, invoked with `python -m tests.<module>`.

## Architecture

### The core rule: `core/` is frozen, `skills/` is where everything happens

The entire system is designed around one constraint: **`core/` is built once and essentially never touched
again.** All new functionality is added by dropping a new `skills/skill_<name>.py` file — no registration
step, no edits to existing files. Removing a feature means deleting its file. When asked to add a feature,
the default move is "write a new skill file", not "extend the router/dispatcher".

`voice/` (audio I/O) and `ui/` (web dashboard) are likewise kept fully decoupled from `core/`: core only
emits text in/out and status events, and never knows whether the input came from a microphone or a chat box.

### Pipeline

```
input text -> Router.route() -> Skill | None -> Dispatcher.dispatch() -> SkillResult
```

- **`core/registry.py`** (`SkillRegistry`) — glob-scans `skills/skill_*.py` on startup, `exec_module`s each
  file, and instantiates every concrete `Skill` subclass found. A broken skill file is caught and logged
  without affecting the others. `reload()` re-scans at runtime.
- **`core/router.py`** (`Router`) — calls `can_handle(intent, text) -> float` on every loaded skill and picks
  the highest score. If the best score is below the threshold (`_DEFAULT_THRESHOLD = 0.4` in `router.py`,
  *not* currently read from `config/settings.yaml` — see Gotchas below), it returns `None` to signal "AI
  fallback needed".
- **`core/dispatcher.py`** (`Dispatcher`) — runs the chosen skill's `execute()`, catching exceptions so one
  skill failing never crashes the loop. If `Router` returned `None`, it falls back to whichever skill is
  named `"ai_chat"` (see `skills/skill_ai_chat.py`). Emits `StatusEvent`s (`processing` → `responded`) via
  the global `broadcaster`.
- **`core/skill_base.py`** — the `Skill` ABC and `SkillResult` dataclass. This is the contract every skill
  must satisfy:

  ```python
  class MySkill(Skill):
      name = "my_skill"               # lowercase_with_underscores, unique
      description = "one-line description for the router"
      triggers = ["키워드1", "키워드2"]
      examples = ["예시 문장"]

      def can_handle(self, intent: str, text: str) -> float:  # 0.0–1.0 confidence
          ...

      def execute(self, text: str, context: dict) -> SkillResult:
          return SkillResult(speech="...", success=True, data={}, follow_up=False)
  ```
  `context` is `ConversationContext.to_dict()`: `{"history": [Turn, ...], "data": {...}}`. `follow_up=True`
  on the result tells the voice loop to skip waiting for the wakeword on the next turn (multi-turn exchange).
- **`core/context.py`** (`ConversationContext`) — shared turn history (capped, default 20) plus a free-form
  `dict` for cross-skill session state (`get`/`set`/`delete`). One instance is shared by `Router`/`Dispatcher`
  for the lifetime of a run.
- **`core/input_channel.py`** — normalizes voice STT output and chat text into the same `InputEvent`. Also
  tracks consecutive STT failures (`record_stt_failure()`); after 3 (`_STT_FAIL_LIMIT`) it signals (via a
  status event) that the caller should fall back to chat mode. Voice failing must never stop the assistant —
  this is a deliberate design invariant, not an incidental detail.
- **`core/status_events.py`** — `StatusBroadcaster` (singleton instance `broadcaster`) is the *only* channel
  through which `core/` talks to the UI layer: it emits `idle | listening | processing | responded` events.
  `ui/server.py` subscribes to it and relays over WebSocket. Nothing in `core/` imports from `ui/`.
- **`core/engines/claude_code.py`** (`ClaudeCodeEngine`) — shells out to
  `claude -p <prompt> --output-format json` with an environment variable **whitelist** (`_ENV_WHITELIST`),
  injects `config/persona.md` as a system-style preamble, parses the JSON result, and records
  `total_cost_usd` via `core/usage.py` into `data/usage.json` (used for the daily-budget usage gauge in the
  UI, default budget `$1.00/day`). Never raises outward — all failure modes (timeout, missing `claude` on
  PATH, non-zero exit, bad JSON) degrade to a Korean error string.
- **`core/engines/groq_engine.py`** (`GroqEngine`) — calls the Groq SDK's `chat.completions.create()` directly
  (model/max_tokens/temperature/timeout default from constants, overridable via `settings.yaml`'s `groq:`
  section), injects `config/persona.md` as a `system` message, and never raises outward — every Groq SDK
  exception (`AuthenticationError`, `RateLimitError`, `APITimeoutError`, `APIConnectionError`, generic) maps to
  a Korean error string. The `GROQ_API_KEY` check is deliberately lazy (inside `ask()`, not `__init__`) so a
  missing `.env` key can't crash `SkillRegistry` loading. Every response is also checked for Han/Hiragana/
  Katakana characters (`_FOREIGN_SCRIPT` regex) — Llama 3.3 occasionally leaks a stray CJK character into
  otherwise-Korean text (observed in production, e.g. "더詳細한 정보"); on detection it retries up to
  `_MAX_ATTEMPTS` (3) times, and as a last resort strips the offending characters rather than show them raw.
  Records token usage into `data/groq_usage.json` via `core/groq_usage.py` (TPD-based %, *not* the same gauge
  as Claude's `data/usage.json`, which is $ cost-based) on every attempt, including retries.
- Both engine classes expose the same `ask(text: str) -> str` interface, and `skills/skill_ai_chat.py` imports
  whichever one is active under a shared alias (`as Engine`) — swapping engines is a one-line import change
  there, with the unused one's import line kept as a commented-out `# [ROLLBACK]` line for quick reversal.
  `GroqEngine` additionally exposes `generate(prompt, system=None) -> str`, which *adds* `system` on top of
  `persona.md` rather than replacing it (replacing it once caused the Korean-only instruction to silently drop
  for weather/search responses) — both `ask()` and `generate()` share one private `_complete()` that does the
  actual API call + error mapping + retry/usage-recording.
- **Both engines implement `describe() -> dict`** (`{"provider", "model", "connected", "usagePercent"}`) —
  this is how `ui/server.py` populates the dashboard's left panel without needing to know which engine is
  active. `ui/server.py`'s `_engine_descriptor()` finds the `ai_chat` skill in the registry, reads its
  `_engine` attribute, and calls `.describe()` on whatever's there. If you add a third engine, implementing
  `describe()` on it is what makes the UI show it correctly.
- **`core/search_engine.py`** (`SearchEngine`) — free web search for `skills/skill_web_search.py`. Defaults to
  DuckDuckGo (`ddgs` package — `duckduckgo_search` is the deprecated predecessor, don't reinstall that one) and
  switches to Brave Search automatically if `BRAVE_SEARCH_API_KEY` is set in `.env`. `search()` never raises —
  any failure (bad key, network, rate limit) logs and returns `[]`, so callers always get a list back.
  `skill_web_search.py` scores itself defensively in two tiers: a small set of search-specific words
  ("뉴스"/"환율"/"주가"/"검색"/"찾아") score 0.8 alone, but generic conversational words ("오늘"/"지금"/"어때"/
  "알려줘"/"최신") score only 0.3 alone (below the router's 0.4 threshold) and need a strong word alongside
  them to win — this two-tier split exists specifically to avoid repeating the bug where `skill_window.py`'s
  bare `"창" in text` check hijacked unrelated sentences containing "곱창" (see git history around that fix if
  you need the full story). Web search is deliberately *not* used for weather — see next bullet.
- **`core/weather_client.py`** (`WeatherClient`) — current weather via Open-Meteo (free, no API key) for
  `skills/skill_weather.py`. Important gotcha verified by hand: Open-Meteo's geocoding endpoint barely works
  for bare Korean place names — `"서울"` returns zero results, `"대전"` returns small unrelated villages (and
  even a North Korean namesake) instead of the actual metro city, and `"Jeju"` alone resolves to a place in
  Ethiopia. The fix is `_ROMANIZED_CITIES`, a hardcoded Korean→English lookup table for ~50 major Korean
  cities/counties (each verified individually against the live API before being added) — `_geocode()` looks up
  the romanized name there first, then always filters results to `country_code == "KR"` and picks the
  highest-population match. A place not in that table fails with a clear "위치를 찾지 못했습니다" rather than
  silently resolving to the wrong country. `skill_weather.py` claims "날씨"/"기온"/"미세먼지"/"체감온도"/
  "강수확률" at a flat 0.85 (no weak tier needed — these words are specific enough on their own).

### Two independent runtime entry points

`main.py` (voice/text loop) and `ui/server.py` (FastAPI dashboard, run via `uvicorn`) each construct their
**own** `SkillRegistry` / `Router` / `Dispatcher` / `ConversationContext`. They are not the same process and
do not share conversation state — running both gives you two independent "sessions" against the same skill
set. `ui/server.py`'s docstring notes that wiring uvicorn into `main.py`'s process (e.g. as an asyncio task)
is an intentional non-goal of that file.

### Skill routing/scoring convention

Skills score themselves defensively, not just by keyword presence — e.g. `skill_app_control.py` deliberately
returns a low score (0.3) for ambiguous "꺼줘" without a known app name so that a more specific skill (like
volume's "소리 꺼줘") can win instead. `skill_ai_chat.py` always returns `0.1`, low enough to never be picked
directly, only reached via the `Router -> None -> Dispatcher fallback` path. Follow this pattern for new
skills: prefer returning a low/zero score over guessing, and let the AI fallback handle genuine ambiguity.

### Voice layer (`voice/`, Windows-native only)

- `stt.py` — `silero-vad` detects speech boundaries, `faster-whisper` ("base" model, Korean) transcribes.
  Input device is picked by matching `"mic"` in the device name (Korean driver names get mangled by
  PortAudio but the English suffix survives) since the OS default input device is unreliable on this setup.
  Audio is captured at the device's native sample rate via callback stream (WDM-KS backend requirement) and
  resampled to 16kHz for VAD/Whisper.
- `wakeword.py` — `wait_for_activation()` blocks until either trigger fires, racing two detectors on the same
  audio stream: `openWakeWord`'s pretrained `"hey_jarvis"` ("Hey Jarvis") English model (a Korean "자비스"
  wakeword model does not exist yet — `_WAKEWORD_NAME` is the single swap point for when one is trained), OR
  `clap_detector.ClapDetector` (double-clap). Returns `"wakeword"` or `"clap"`.
- `clap_detector.py` — pure double-clap heuristic (peak-amplitude onset + refractory + max-gap window), no
  I/O — deliberately separated from `wakeword.py` so it's unit-testable without a mic (`tests/test_clap_detector.py`).
  Thresholds are hardcoded heuristics tuned by eye, not calibrated per-environment; expect to retune
  `_PEAK_THRESHOLD` if real-world use shows false positives/negatives.
- `tts.py` — `edge-tts` synthesis.
- `text_input.py` — console input used by `--text` mode.
- `main.py`'s voice loop is **always-on once activated**: after `wait_for_activation()` fires, it keeps
  calling `stt.listen()` in a loop (ignoring `SkillResult.follow_up` — continuous mode supersedes it)
  regardless of silence/timeouts, until the transcribed text matches `_is_deactivate_command()` (normalized
  prefix match on "자비스오프"/"자비스종료" — deliberately a *prefix* check so it doesn't fire on commands like
  "자비스 크롬 종료해줘" where another word sits between "자비스" and "종료"). The bare `_EXIT_WORD = "종료"` is a
  separate, unrelated check that quits the whole program, not just the listening session.

### UI layer (`ui/`)

- `ui/server.py` — FastAPI app exposing `GET /api/status` (snapshot), `POST /api/chat` (text in,
  `channel="chat"` so TTS is never invoked for it), and `WS /ws` (live status push). CORS is locked to the
  Vite dev origins (`localhost:5173`).
- `ui/web/` — separate npm project (React 18 + TypeScript + Vite). `useJarvisStatus.ts` is the shared hook
  both UI modes (`JarvisMinimal`, `JarvisFull`) subscribe to for live state.
- **Clearing chat history** (`/clear` in chat, `"채팅 목록 지워줘"` etc. in voice/`--text`) is handled by
  pattern-matching directly in `_handle_chat()` (`ui/server.py`) and the loops in `main.py` — *not* a skill,
  same precedent as `_EXIT_WORD`/`_is_deactivate_command`. `_handle_chat()` intercepts `/clear` **before**
  calling `Router`/`Dispatcher`, deliberately — going through `Dispatcher` would also fire
  `broadcaster.emit(state="responded", ...)`, racing the WebSocket-pushed "cleared" turn against the
  HTTP response's `cleared: true` flag that the frontend uses to reset `conversationLog` to `[]`. Both entry
  points call `core/context.py`'s `ConversationContext.clear()` plus `core/chat_history.py`'s
  `clear_history()` (moved here from `ui/chat_history.py` since voice-triggered clearing needs to write the
  same shared `data/chat_history.json` that the web dashboard reads — `main.py` and `ui/server.py` are
  separate processes with no other shared state, so the file is the only thing voice-side clearing can
  actually affect; an already-open browser tab won't reflect it without a refresh).

## Gotchas

- **`config/settings.yaml` is mostly not read by any code.** Values like `router.threshold`,
  `voice.stt_fail_limit`, `engine.timeout` exist there but the real values are hardcoded as module-level
  constants in `core/router.py`, `core/input_channel.py`, `core/engines/claude_code.py`, etc. Treat the YAML
  as a (currently aspirational) reference, not the source of truth — if you change a tunable, change the
  constant in code, and consider whether wiring it through `settings.yaml` is actually in scope.
  **Exception:** the `groq:` section *is* actually read, by `core/engines/groq_engine.py`'s
  `_load_groq_settings()` — it overrides that file's hardcoded defaults (model/max_tokens/temperature/timeout)
  if present.
- Several skills (`skill_volume.py`, `skill_window.py`) depend on Windows-only packages (`pycaw`,
  `pygetwindow`) and import them lazily inside `execute()` so the rest of the app still loads if those
  packages are missing.
- `__pycache__` directories at the repo root and inside packages are stale build artifacts, not source.

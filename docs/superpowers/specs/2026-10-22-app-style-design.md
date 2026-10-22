# App-wide style, control bar, listen/speak states, Echo + Flow only

Agreed with the user on 2026-10-22, step by step against browser mockups (`.superpowers/brainstorm/571518-1792687691/content/`: `control-bar-v2.html`, `palette-v2.html` option A, `listen-speak.html`; git-ignored, on this machine). Built **before** the Stats redesign (`2026-10-22-stats-redesign-design.md`), which then uses this style.

## 0. Intent

**What the user asked for.**
- A style that is consistent throughout the app and unique.
- Night-mode friendly, Chinese colours, and "intuitive UI like Steve Jobs principles".
- The bottom control bar is "not intuitive":
  - the most-used actions (next/previous sentence, play reference, play my take, send to Anki) have small, illogically placed buttons;
  - previous and next are far apart;
  - icons don't say what the button does and look like hotkeys (Space shows ▶, which reads as "navigate right");
  - C shouldn't be a button;
  - volume and speed should be a pop-up;
  - nobody knows what F / T / P / E do;
  - Finish session isn't needed.
- The waveforms and the "when to listen / when to speak" indication should change: "your turn" must be more in focus and bigger, and the countdown must not use the same dots as the mic level.
- "There are way too many modes": keep **Echo** and **Flow** only. Keep both Flow variants.

**Success.** On any page, the user's eyes know where to go and his hands know which key. Listening vs speaking is unmistakable from across the room. The app looks like one thing, and like itself.

**Anti-goals.**
- Pages styled one by one, so they drift apart again.
- Ornament that costs clarity: the Chinese motif decorates, it never hides a control.
- Bright surfaces at night.
- A key that does something different from what its button says.

**Not in scope.**
- A light theme.
- Mobile layouts beyond "nothing breaks at narrow widths".
- New features.
- Changing scoring.

## 1. Look

### 1.1 Palette ("Lacquer", option A)

the user's two anchor colours from his reference picture are **佛手黄 #F5CB00** and **古铜紫 #4E001B**. All colours are design tokens, defined once and used by name everywhere; no hex values in components.

| token | value | use |
|---|---|---|
| `bg` | `#2b0510` | page background (darkest 古铜紫) |
| `panel` | `#3d0a1b` | bars, panels, top navigation |
| `card` | `#4E001B` | the sentence card, buttons, Stats cards, lesson tiles |
| `line` | `#6b1a33` | borders, dividers |
| `fg` | `#f6ead8` | main text |
| `fgdim` | `#c7a9a0` | secondary text, key hints |
| `accent` | `#F5CB00` (佛手黄) | the one thing to look at: pinyin, ▶ Listen, active tab, position (12/48), focus rings |
| `ref` | `#d6e6ea` (月白) | the speaker: their waveform, pitch line, reference row |
| `you` | `#F5CB00` (佛手黄) | you: your waveform, pitch line |
| `ok` | `#2bae85` (碧, jade) | tone right |
| `warn` | `#f0a020` (杏黄, apricot) | tone close |
| `bad` | `#ff5a3c` (朱, vermilion) | tone wrong |
| `sound` | `#cca4e3` (丁香, lilac) | a wrong sound (replaces `#c678dd`); still reserved for sounds only |
| `record` | `#cb2c1b` | the Record button and the "your turn" frame (nudged from `#e0301e` for AA contrast) |

- Verdict cells use their colour as border plus a ~18 % tint as background.
- Text on any token background meets WCAG AA (4.5:1). The builder checks every pair and may nudge values slightly to get there, keeping the hue.

### 1.2 Shape and type

- **Window-frame corners.** The notched corners from the user's picture (an octagonal clip of about 12–14 px) go on **main cards only**: the sentence card, Stats score cards and lesson tiles. Buttons, chips and inputs are simply rounded (about 12 px). *My call*, so the motif stays special.
- **Characters** in a Song/Ming-style serif: Noto Serif SC, bundled locally with `@fontsource` like the current fonts. No CDN. Pinyin, labels and numbers stay in the current Inter. *My call.*
- One spacing scale, one radius scale and one type scale, as tokens.

### 1.3 Principles (from "Steve Jobs" simplicity)

- One obvious main action per screen: Record on Practice and Drill, Start on the Drill start screen, the score cards on Stats.
- Buttons say what happens, as an icon plus a word. The shortcut key is shown small and grey **under** the label, never as the button's face.
- Settings and rarely used controls live in pop-ups, not on the main bar.
- The same action has the same icon, word and key on every page.

## 2. Control bar (Practice and Drill)

Three groups, left to right (mockup `control-bar-v2.html`):

1. **Where am I:** ‹ `12 / 48` ›. Previous and next sit together around the position, using thin chevron icons. Keys ← / →.
2. **What do I do:**
   - **▶ Listen**: a solid play triangle, plays the reference. Key Space.
   - **● Record**: large, `record` colour. Key Enter. While recording it shows ■ Stop and stops by itself after the silence that follows speech (as now).
   - **Me**: a person icon, plays your take, trimmed to your voice. Key R.
3. **Extras:**
   - **Anki**: send this sentence to the listening deck. Key A.
   - **Sound**: the speaker icon, which belongs to sound settings. It opens a pop-up with playback speed (including the old 0.75× preset), speaker volume and guide level.

Moved off the bar:
- **⚑ Difficult** (F) and **字 / pīn / EN** (T / P / E: show or hide characters, pinyin, English) sit next to the sentence, on the sentence card.
- **Finish session** is removed. The existing "send what you practised to Anki" offer appears when the user leaves the lesson (navigates away), when there is something to offer. *My call.*
- **C** goes with Chorus (§4).

The Drill page uses the same bar, with the same keys in the same places. Drill-only controls (Next / Again, Finish drill) sit where they are now, styled the same.

## 3. Listen / get ready / your turn

Mockup `listen-speak.html`. The **whole stage** shows the state; there is no text line plus mic meter.

1. **Listen.**
   - The speaker's waveform (`ref`) fills in as the clip plays, with the karaoke wipe over the characters.
   - A small, calm "▶ Listening" label.
2. **Get ready.** Only where timing matters: Flow, both variants.
   - A big **3 · 2 · 1** in `accent`, centred over the stage, inside a ring that runs down.
   - It replaces the ● ● ● count-in dots.
   - Echo has no countdown; it goes straight to "Your turn" as now.
3. **Your turn.**
   - The stage gets a `record`-coloured frame.
   - Large **"Your turn"** text with a pulsing red dot and a timer (0:02).
   - the user's **live waveform** (`you`) grows as he speaks and goes flat in silence. This is the mic check, replacing the small mic meter.
   - In Flow *along*, the same frame and live waveform show while speaking along.

Dots are no longer used for anything.

## 4. Modes: Echo and Flow only

- **Practice offers Echo and Flow.** Flow keeps both variants: **after** (repeat in the gap after each sentence) and **along** (speak with the speaker), as a small switch inside Flow.
- **Chorus and Guided are removed:** the mode switch entries, their run logic, help texts, the C key and guided cue texts.
- **Drills stay**, on their own page.
- **Old takes stay.** Attempts recorded as `chorus` or `guided` stay in history, Stats and exports; the backend keeps accepting those mode values for old data.
- The settings that only applied to removed modes (`chorus_passes`) go too, if nothing else uses them.

## 5. Waveforms

- Rounded bars.
- The played part is full colour and the unplayed part about 35 % opacity, so the bars fill in as they play.
- Speaker in `ref`, you in `you`.
- Syllable boundaries are shown as subtle gaps or faint ticks in `line`, not hard grey lines. *My call.*
- The playhead is a thin `fg` line.
- Pitch lines follow the same colours.
- The review block (TwoTrack, HEARD row, cells) keeps its structure from Phase 3a, restyled with the tokens.

## 6. Every page

- One shared set of tokens and components (buttons, chips, cards, pop-ups, dialogs, tabs) drives every page: Library, Practice, Drill, Stats (current page until the redesign), Review, Settings, and the Anki and edit dialogs.
- The top navigation uses `panel` with the active tab underlined in `accent`.
- Dark only. **No white or light surfaces anywhere**, including dialogs and native form controls; style `select` and `range` inputs to match.
- The help overlay (?) lists the new keys: ←/→, Space, Enter, R, A, F, T/P/E, L (drawer), ?.

## 7. Left to the builder

- Exact icon set: inline SVG in the mockups' style, consistent stroke.
- Transitions: subtle, ≤ 200 ms; none that delay the "your turn" moment.
- Component file structure, and how tokens map into Tailwind (the existing `tailwind.config.ts` colours become these tokens).
- Accessibility: focus rings in `accent`, `aria-label`s on icon buttons, contrast checks per §1.1.
- Tests: existing behaviour tests keep passing except where §2–§4 change behaviour (removed modes and keys, the moved controls, the removed Finish session). Those tests change with it.

## 8. Builder questions settled (my calls, 2026-10-22)

- **Countdown.** Wherever Flow has a count-in today (both variants), it becomes the 3 · 2 · 1 ring with **the same timing**: no new pauses. Echo shows no countdown (the user approved "Flow only"); Echo's current count-in dots are simply dropped, and its timing is unchanged.
- **Keys.**
  - **S** (0.75× speed) stays as a shortcut and is listed in the help overlay. The Sound pop-up shows the same preset.
  - **C** is removed with Chorus.
  - The final key list: ←/→, Space, Enter, R, A, S, F, T/P/E, L, ?.
- **Guide level** is the existing setting (`guideLevel`: the reference volume while speaking along). It stays for Flow *along* and lives in the Sound pop-up.
- **Old modes in data.** The `Mode` type and display labels keep `chorus` and `guided` for old attempts (Stats, Review, flow-run lists). Only the run logic, mode switch, help and cue texts go. `chorus_passes` can be removed from config: `Settings` ignores unknown keys, so an old `config.toml` still loads.
- **Drill** uses the same stage component as Echo: Listen, then "Your turn" with the record frame and live waveform. Its Next / Again / Finish drill stay where they are, styled like the bar. The same keys do the same things.
- **Sound pop-up.**
  - A non-modal popover: it does not take `role="dialog"`, so Space and Enter keep working.
  - It closes on Esc or an outside click.
  - `role="dialog"` stays reserved for modals.
- **Sentence-card tools** (⚑ Difficult, 字 / pīn / EN) appear on the card in Practice and Drill.
- **Serif font.** Noto Serif SC through `@fontsource`, simplified-Chinese subset slices only, weights 400 and 600, bundled locally.
- **Colour priority.**
  - Keep the tokens as given and nudge only for AA contrast.
  - `you` = `accent` is intended: it is the user's colour.
  - `record` and `bad` may stay close, because one is a button and the other a verdict.


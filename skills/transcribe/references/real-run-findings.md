# real-run findings

This file keeps the operational and historical findings that used to sit inside `SKILL.md`.

Use it when you are debugging regressions, comparing prompt variants, or auditing replay runs. Keep `SKILL.md` focused on the active workflow and runtime contract.

## Core operating lessons

- If Step 1 is blocked, replay from an existing `raw.json` so Step 2 and Step 3 stay testable.
- Review `run_glossary.json` on every real sample. If it contains sentence fragments or long contextual phrases, tighten the candidate filters.
- Review `edited-script-pass.srt` for tiny cues and collapsed tails. Those belong in Step 2 micro-cue merge guards and Step 3 adjudication.
- Use `report.json` to watch draft mode, fallback reasons, downgrade signals, short cue counts, suspicious glossary terms, and final delivery state.
- Judge real usability from real run directories. `edited.srt` and `final_delivery_audit.json` are the first artifacts to inspect.

## Replay and alignment findings

- A real FunASR + manuscript run can start as `manuscript-priority` and still downgrade to `raw-priority` at audit time. Read `alignment_success_rate`, `fallback_region_count`, and `downgrade_count` together.
- `edited-script-pass.srt` can reintroduce overlong lines in rebuild regions even when `subtitle_draft.json` already obeys the 17-unit cap.
- When one or two over-17 lines remain, inspect `alignment_audit.json` first. Rebuild regions are the common source.
- When rebuilt raw text is longer than the aligned text and adds filler such as `啊` or `这个`, keep the aligned text when it already matches the audio closely.
- If adjacent cues duplicate a boundary, compare `subtitle_draft.json`, `aligned_segments.json`, `edited-script-pass.srt`, and `edited.srt` for the same pair before changing code.
- If a micro-cue survives into `edited.srt`, inspect neighboring boundary warnings as well as the cue's own warning fields.

## Glossary and entity recovery findings

- Watch for manuscript-backed entity recovery overreach. A recovered term can duplicate nearby wording.
- Watch for manuscript-backed entity recovery underreach. Mixed-script entities such as `埃安 S` or `岚图 Free` can survive as ASR noise unless local anchor matching is strong enough.
- Watch for manuscript orthography loss on terms such as `自働化` when the manuscript is the authoritative source.
- A dedicated direct DeepSeek provider restored useful Step 2A glossary corrections on replay runs, including `ins -> 埃安 S`, `iny -> 埃安 Y`, and `自动化 -> 自働化`.

## Prompt and contract findings

- Step 2A prompt stability depends on three things staying aligned: punctuation-free output, the 17-unit cap, and JSON field names.
- `deepseek-v4-flash` can spend most of its budget in `reasoning_content`. Long Step 2A JSON outputs need a large output budget and a parser that checks both `message.content` and `reasoning_content`.
- Short priority-ordered prompts produced the cleanest default behavior on the main replay sample.
- Mixed-script spacing reminders helped preserve forms such as `埃安 S`, `岚图 Free`, `A 阶段`, and `JR 福知山线`, while also increasing over-splitting pressure.
- A prompt body that still emits legacy labels such as `proofread_manuscript:` and `subtitle_draft:` can break the JSON contract. Keep prompt body and wrapper schema aligned.
- Serial-token guidance such as `A-B-C-D -> A B C D` improved punctuation compliance and reduced contract failures.

## Step 3 delivery findings

- A Step 3 pass should create true cue-level re-segmentation when rhythm and timing support it.
- Internal line wrapping inside one unchanged cue timestamp is the wrong delivery shape for this workflow.
- Subtitle length policy targets comfortable rhythm around 12 Chinese-character-equivalent units per cue, with 17 units as the hard maximum.
- Keep delivery checks and alignment risk separate. A run can have clean punctuation and line length while still carrying alignment or downgrade risk.

## Credential visibility findings

When a previously working Bailian / DashScope key seems to have disappeared:
- Check the live agent process environment first.
- Check common variable names: `DASHSCOPE_API_KEY`, `BAILIAN_API_KEY`, `FUNASR_API_KEY`, and `ALIYUN_BAILIAN_API_KEY`.
- Inspect shell startup files and nearby `.env` files.
- On macOS, `launchctl getenv KEY` helps confirm user launch environment visibility.
- If the active run cannot see the key, restore visibility or replay from an existing FunASR `raw.json`.

## Architecture pressure

The target workflow is manuscript-first subtitle production:
1. proofread the manuscript against audio
2. semantically segment it into one subtitle line per unit
3. align those lines back onto audio timing
4. let the live agent deliver the final judgment

The intended control shape stays model-led:
- Step 2A auxiliary drafting and Step 3 Hermes hold text-quality authority.
- Scripts provide alignment, validation, serialization, reporting, and guardrails.
- Step 3 prompt and workflow truth are high-priority maintenance surfaces.
- Replay usability is a high-priority maintenance surface.

## Suggested audit flow for a real replay

1. Read `report.json` for route, draft mode, downgrade state, and final delivery state.
2. Read `run_glossary.json` for suspicious entries.
3. Read `subtitle_draft.json` for segmentation quality and line length.
4. Read `edited-script-pass.srt` for rebuild-region regressions and cue collapses.
5. Read `edited.srt` and `final_delivery_audit.json` for actual deliverability.

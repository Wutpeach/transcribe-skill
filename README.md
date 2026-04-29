# transcribe-skill

Cross-agent share repo for the `transcribe` skill.

This repository packages the skill in a standard `skills/<name>/SKILL.md` layout so it can be discovered by the open agent skills ecosystem.

## Install with `npx skills`

List skills in this repo:

```bash
npx skills add Wutpeach/transcribe-skill --list
```

Install from GitHub:

```bash
npx skills add Wutpeach/transcribe-skill
```

Install the `transcribe` skill explicitly:

```bash
npx skills add Wutpeach/transcribe-skill --skill transcribe
```

## Hermes manual install

If you want to use this skill in Hermes directly, copy:

```text
skills/transcribe
```

into:

```text
~/.hermes/skills/custom/transcribe
```

## Local configuration

The repo excludes machine-local secrets.

After installation, create your local FunASR config from the example file:

```bash
cp config/funasr.local.example.toml config/funasr.local.toml
```

Then fill in your own credentials, or provide `DASHSCOPE_API_KEY` through the environment.

## Layout

```text
skills/
  transcribe/
    SKILL.md
    scripts/
    prompts/
    tests/
    references/
    config/
```

## Notes

- `config/funasr.local.toml` is intentionally excluded.
- `.env.local`, caches, and Python bytecode are excluded.
- The public default config stays in `config/funasr.toml`.

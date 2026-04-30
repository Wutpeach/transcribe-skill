# transcribe-skill

跨 Agent 平台的转录与字幕 skill。

适用于 Hermes、OpenClaw、pi agent、nanobot、Codex CLI 等能够在本地运行 skill、读写文件并提供 API key 的宿主。

这个 skill 用来把音频处理成可交付的 SRT 字幕。它把原始识别、术语处理、字幕切分、时间对齐和最终审校拆成清晰步骤，适合对术语准确性、断句质量和时间轴稳定性有要求的任务。

## 适用场景

- 技术分享、课程录音、产品讲解
- 访谈、播客、口播内容
- 有讲稿或参考文稿的音频
- 需要保留术语、英文缩写、大小写和中英混排质量的字幕任务

## 这个 skill 会做什么

- Step 1：用 FunASR 产出带时间信息的原始转录
- Step 2：结合 manuscript 和 glossary 做文本校对、字幕切分、时间对齐和审计
- Step 3：由当前运行中的 live agent 做最终裁决，输出可交付的 `edited.srt`

整个流程会保留中间产物，方便复查、调试和回放。

## 主要产物

- `raw.json`：原始转录和时间信息
- `edited-script-pass.srt`：对齐后的中间字幕稿
- `edited.srt`：最终交付字幕
- `report.json`：本次运行的摘要和状态

完整运行规则、artifact 说明和命令细节见 [`skills/transcribe/SKILL.md`](skills/transcribe/SKILL.md)。

## 快速安装

### 用 `npx skills` 安装

```bash
# 查看这个仓库里的 skill
npx skills add Wutpeach/transcribe-skill --list

# 安装 transcribe
npx skills add Wutpeach/transcribe-skill --skill transcribe
```

### Hermes 手动安装示例

把下面这个目录：

```text
skills/transcribe
```

复制到：

```text
~/.hermes/skills/custom/transcribe
```

## 运行要求

建议宿主机提前具备：

- `git`
- `node`
- `npx`
- `python3`
- `python3 -m pip`

Python 版本要求见 `skills/transcribe/pyproject.toml`。当前项目要求 `Python >= 3.11`。

## 本地配置

安装完成后，先进入 skill 目录，再创建本地配置和本地 env：

```bash
cp config/funasr.local.example.toml config/funasr.local.toml
cp .env.example .env.local
```

### Step 1：FunASR

FunASR 的 base URL 固定在 `config/funasr.toml`。安装时只需要向用户索取 FunASR / DashScope API key，并写入：

- `config/funasr.local.toml`
- 或本地环境变量 `FUNASR_API_KEY` / `DASHSCOPE_API_KEY`

### Step 2A：辅助模型

Step 2A 按 OpenAI-compatible 接口理解。安装时向用户索取：

- `AUXILIARY_BASE_URL`
- `AUXILIARY_API_KEY`

把它们写入 `.env.local`、`config/auxiliary.local.toml`，或宿主管理的本地环境配置。

如果这组辅助模型配置不完整，skill 会回退到**当前 live agent 自身运行时**提供的模型入口，而不是绑定某个固定的宿主 provider alias。

这个 live agent runtime 可以由宿主直接注入，也可以通过 `CURRENT_LIVE_AGENT_BASE_URL`、`CURRENT_LIVE_AGENT_API_KEY`、`CURRENT_LIVE_AGENT_API_MODE`、`CURRENT_LIVE_AGENT_PROVIDER_NAME` 这组环境变量提供。

如果 Step 2A 的辅助模型请求本身失败，当前 live agent 会直接接管 Step 2 的 proofreading 和 segmentation，产出 Step 2 artifact，再把结果继续交给 Step 3 做原流程里的最终审校。此时 `draft_model_provider` 会标记成 `local-helper`，表示 fallback 产物来自本地 helper 逻辑。

本地 secret 只保留在本机，不进入仓库。

### 配置文件说明

- `config/funasr.toml`：FunASR 公共默认配置
- `config/funasr.local.toml`：FunASR 机器本地 secret 和覆盖项
- `.env.local`：Step 2A 辅助模型等机器本地 env
- `config/auxiliary.local.toml`：Step 2A 可选本地覆盖配置
- `config/models.toml` / `config/transcribe.toml`：Step 2A 模型与流程配置

## 验证安装

在 skill 目录里运行：

```bash
python3 -m pip install .[dev]
python3 scripts/pipeline.py --help
PYTHONPATH=scripts pytest tests/test_prompts.py -q
```

验证通过后，这个 skill 就处于可运行状态。

## 仓库结构

```text
skills/
  transcribe/
    SKILL.md
    pyproject.toml
    scripts/
    prompts/
    tests/
    references/
    config/
```

## 给 agent 的安装流程

用户把这个仓库链接发给你之后，直接完成下面这些事：

1. 检查宿主机是否具备 `git`、`node`、`npx`、`python3`、`python3 -m pip`
2. 缺少依赖就先补齐
3. 用 `npx skills add Wutpeach/transcribe-skill --skill transcribe` 安装，或手动复制 `skills/transcribe`
4. 进入安装后的 skill 目录
5. 运行 `python3 -m pip install .[dev]`
6. 如果 `config/funasr.local.toml` 不存在，就从模板复制生成
7. 如果 `.env.local` 不存在，就从 `.env.example` 复制生成
8. 向用户索取 FunASR / DashScope API key，并写入本地配置或本地环境变量
9. 向用户索取 Step 2A 辅助模型的 OpenAI-compatible base URL 和 API key，并写入 `.env.local` 或宿主管理的本地环境配置
10. 运行验证命令，确认 skill 可直接使用

完成后让机器保持 ready-to-run 状态。

## 说明

- `config/funasr.local.toml`
- `.env.local`
- 缓存目录
- Python bytecode

这些本地文件都应保持在 git 之外。

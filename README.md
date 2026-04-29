# transcribe-skill

面向 Hermes 类 agent 的转录与字幕 skill。

这个 skill 用来把音频处理成可交付的 SRT 字幕。它把原始识别、术语处理、字幕切分、时间对齐和最终审校拆成清晰步骤，适合对术语准确性、断句质量和时间轴稳定性有要求的任务。

## 适用场景

- 技术分享、课程录音、产品讲解
- 访谈、播客、口播内容
- 有讲稿或参考文稿的音频
- 需要保留术语、英文缩写、大小写和中英混排质量的字幕任务

## 这个 skill 会做什么

- Step 1：用 FunASR 产出带时间信息的原始转录
- Step 2：结合 manuscript 和 glossary 做文本校对、字幕切分、时间对齐和审计
- Step 3：由 live agent 做最后一轮判断，输出可交付的 `edited.srt`

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

### 手动安装到 Hermes

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

安装完成后，先进入 skill 目录，再创建本地配置：

```bash
cp config/funasr.local.example.toml config/funasr.local.toml
```

然后把你的 DashScope / FunASR API key 写进去，或者使用本地环境变量：

```bash
DASHSCOPE_API_KEY=...
```

本地 secret 只保留在本机，不进入仓库。

### 配置文件说明

- `config/funasr.toml`：公共默认配置
- `config/funasr.local.toml`：机器本地 secret 和覆盖项
- `config/models.toml` / `config/transcribe.toml`：Step 2 辅助模型与流程配置

## 验证安装

在 skill 目录里运行：

```bash
python3 -m pip install -e .[dev]
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
5. 运行 `python3 -m pip install -e .[dev]`
6. 如果 `config/funasr.local.toml` 不存在，就从模板复制生成
7. 向用户索取 DashScope / FunASR API key；用户没有 key 时，引导注册和获取
8. 把 key 写入本地配置或本地环境变量
9. 运行验证命令，确认 skill 可直接使用

完成后让机器保持 ready-to-run 状态。

## 说明

- `config/funasr.local.toml`
- `.env.local`
- 缓存目录
- Python bytecode

这些本地文件都应保持在 git 之外。

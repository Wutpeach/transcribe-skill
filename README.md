# transcribe-skill

Hermes-like 代理的转录/字幕技能。  
基于 FunASR 实现高精度音频转录，支持术语校正、字幕分割、对齐和最终人工审定，输出可靠的 SRT 文件。

## 功能亮点
- Step 1：FunASR 提供精确时间戳和原始文本  
- Step 2：辅助模型完成术语校正、字幕分割和对齐（支持 manuscript 优先模式）  
- Step 3：由 Hermes 代理完成最终审定和轻量修正  
- 保留原始音频事实，严格控制术语一致性，中文混合英文处理友好  
- 完整 artifact 链路，便于调试和复现

## 快速安装

### 使用 npx skills（推荐）
```bash
# 查看仓库中的 skill
npx skills add Wutpeach/transcribe-skill --list

# 安装 transcribe skill
npx skills add Wutpeach/transcribe-skill --skill transcribe
```

### Hermes 手动安装
把 `skills/transcribe` 目录复制到：
```
~/.hermes/skills/custom/transcribe
```

## 本地配置
安装完成后执行：
```bash
cp config/funasr.local.example.toml config/funasr.local.toml
```
填写你的 Dashscope API Key（或通过环境变量 `DASHSCOPE_API_KEY` 提供）。

详细运行时说明、命令和 artifact 规格请见 [SKILL.md](skills/transcribe/SKILL.md)。

## 仓库布局（供 agent / bootstrap 使用）

```
skills/
  transcribe/
    SKILL.md                 # 运行时核心文档
    scripts/                 # 流水线实现
    prompts/                 # 提示词
    tests/                   # 测试
    references/              # 设计文档
    config/                  # 默认配置
```

**注意**  
- `config/funasr.local.toml`、`.env.local`、缓存和 Python bytecode 已排除  
- 公开默认配置保留在 `config/funasr.toml`

---

*此仓库遵循 open agent skills 生态标准打包，可被 Hermes 及其他兼容代理直接发现和加载。*

---
name: comfy-text2music
description: 用本地 ComfyUI（ACE-Step 1.5 turbo / YuE2）按音乐风格 + 歌词生成歌曲或纯音乐，并把音频文件下载到本地交给用户。当用户说"写首歌""做个 BGM""生成一段音乐""按这个风格出个 demo""配乐"，或给出曲风、歌词、BPM、调性想听到成品时使用。
agent_created: true
---

# Text2Music（ComfyUI 双引擎）

## 这条 skill 干什么

用户给**音乐风格 + 歌词**（或只要纯音乐）→ 改写工作流 → 提交 ComfyUI → 下载音频 → `present_files` 交给用户试听。

## 前置

- ComfyUI `http://192.168.31.197:10003`（已升级到 0.42.0，两个工作流所需模型都已验证在位）。
- 输出目录是 UNC 网络路径 `\\NAS65A682\Web\images`，**本地直读不了**，必须走 `/view` 下载 —— 脚本已处理。

## 两个引擎怎么选

| | `ace`（默认） | `yue2` |
|---|---|---|
| 模型 | ACE-Step 1.5 turbo split-4b | YuE2 3B int8 |
| 流程 | 文本编码 → 8 步采样 → VAE | ABC 编曲规划 → 32 步扩散 → VAE |
| 参数 | 可调 BPM / 调性 / 拍号 / 语言 | 可调 `full` / `melody` 编曲模式 |
| 适合 | 快速出成品、中文流行歌、短视频配乐 | 想要更结构化的旋律与和弦、翻唱旋律线 |

默认用 `ace`：快、参数多、中英文都稳。用户明确要"编曲更讲究 / 旋律线 / 和弦"或 ACE 效果不满意时换 `yue2`。

## 执行方式（只有这一条路径）

```bash
"C:/Users/AI-Space001/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
  "C:/Users/AI-Space001/.workbuddy/skills/comfy-text2music/scripts/text2music.py" \
  --engine ace \
  --style "<曲风 + 配器 + 氛围>" \
  --lyrics "<带段落标签的歌词>" \
  [--duration 60] [--bpm 120] [--key "E minor"] [--lang zh] [--timesig 4] \
  [--mode full] [--seed 31] [--format mp3] --out "<绝对路径>.mp3"
```

歌词很长时用 `--lyrics-file <utf-8 文件路径>`（优先于 `--lyrics`），避免命令行转义和长度问题。
`--dry-run` 只打印改写后的工作流 JSON，不提交，调参排错时很好用。

脚本只用标准库（urllib），managed python 直接跑。内部：探活 → 看队列 → 改工作流 → 提交 → 轮询 history → `/view` 下载。

### 参数

- `--style` 必填。曲风 + 配器 + 情绪 + 速度感，越具体越好。
- `--lyrics` 省略即**纯音乐**，脚本会自动在 style 里补 "纯音乐，无人声，instrumental, no vocals"。
- `--duration` 默认 60 秒。**先出 20–60 秒试听，用户满意再拉到 180–240 秒出完整歌**；长曲耗时明显上升，且歌词量要跟时长匹配（歌词太少会被拉长/重复）。
- `--bpm` / `--key` / `--timesig` / `--lang` 仅 ACE 生效。`--lang` 是语言代码：`zh` / `en` / `ja` / `yue`（粤语）/ `ko`，默认 `zh`。
- `--mode full|melody` 仅 YuE2；`melody` 只生成旋律线，适合做翻唱。
- `--seed` 默认 31。用户说"再来一版"时**先换 seed**，再改风格/歌词。
- `--format mp3`（默认，通用）/ `flac`（无损）。

## 歌词格式

两个引擎都吃带段落标签的结构化歌词，标签是生成编排的关键：

```
【前奏 Intro】
（明亮吉他旋律，鼓点渐入）

【主歌 1】
清晨阳光，洒满城市街巷
打开易到，奔向新的方向

【预副歌】
心中有梦，脚下就有方向

【副歌】
一路向前，迎着灿烂的阳光

【间奏】
（电吉他轻快独奏）

【桥段】
回望一路，多少难忘的时光

【尾声 Outro】
一路有你，未来更闪亮！
```

- 段落标签用 `【】`，常用：前奏 Intro / 主歌 / 预副歌 / 副歌 / 间奏 / 桥段 / 终段副歌 / 尾声 Outro。
- 括号里的舞台提示用来引导器乐段落，但别写太长，否则可能被当歌词念出来。
- 用户只给零散几句或口语化描述时，**先替他整理成带标签的结构**，再传给脚本。
- 粤语歌词把 `--lang yue`，并尽量用粤语书面写法。

## 拿到文件后

1. 必须 `present_files` 把音频交给用户。
2. 一句话交代：引擎、时长、seed、风格关键词，方便用户说"副歌再燃一点"或"换个 seed"。

## 实测数据（2026-11-19，RTX 4090）

| 用例 | 耗时 | 产物 |
|---|---|---|
| ACE 30s 带人声 mp3 | 26.1s | 0.88 MB |
| YuE2 20s 带人声 mp3 | 23.3s | 0.59 MB |
| ACE 20s 纯音乐 flac | 18.5s | 1.15 MB |

生成很快，但**队列里有别人的任务会阻塞**，提交前脚本会打印队列状态，不要清别人的队列。单 GPU，多个请求必须串行提交。

## 已知坑

- 保存节点只保留一个：ACE 原稿同时有 `SaveAudioMP3`(107) 和 `SaveAudioAdvanced`(109)，脚本按 `--format` 删掉另一个，避免重复落盘两份；YuE2 的 mp3 分支是把 `SaveAudioAdvanced` 换成 `SaveAudioMP3`。
- `SaveAudioAdvanced.format` 在 ComfyUI 0.42 是动态 combo，flac 传字符串 `"flac"` 实测可用。
- ACE 的 `TextEncodeAceStepAudio1.5.duration`、`EmptyAceStep1.5LatentAudio.seconds`、`KSampler.seed` 必须同步改，脚本已处理；只改一处会出静音/长度错乱或结果不可复现。
- `timesignature` 只接受 `"2"/"3"/"4"/"6"` 字符串，`keyscale` 用 `"C major"` / `"E minor"` 这类完整名称。
- `generate_audio_codes` 保持 `true`（LLM 生成音频码，质量更好）；除非给了音频参考。
- 用户拿到的是 mp3/flac；要嵌进视频再自行转码。

## 文件

- `scripts/text2music.py` —— 主脚本。
- `workflows/ace_step_1_5_api.json` / `workflows/yue2_api.json` —— 用户提供的 API 格式工作流原稿，脚本在这两份基础上改参数。

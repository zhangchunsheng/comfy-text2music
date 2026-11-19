#!/usr/bin/env python3
"""Text2Music（ComfyUI）—— 输入音乐风格 + 歌词，输出本地音乐文件。

两个引擎：
  ace   ACE-Step 1.5 turbo / split-4b（8 步，快，默认）
  yue2  YuE2 3B（ABC 编曲规划 + 32 步扩散，慢但编曲更结构化）

只依赖标准库（urllib），managed python 可直接跑。

用法：
  python text2music.py --style "轻快励志流行摇滚，阳光热血" \
      --lyrics "【主歌】..." [--engine ace|yue2] [--duration 60] \
      [--bpm 120] [--key "E minor"] [--lang zh] [--seed 31] \
      [--format mp3|flac] [--out D:/out/song.mp3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.join(os.path.dirname(HERE), "workflows")
DEFAULT_HOST = "http://192.168.31.197:10003"
AUDIO_EXT = (".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a")


def http_json(url: str, data=None, timeout: int = 30):
    if data is None:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
    else:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_bytes(url: str, timeout: int = 300):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def load_graph(engine: str) -> dict:
    name = "ace_step_1_5_api.json" if engine == "ace" else "yue2_api.json"
    with open(os.path.join(WF_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def build_ace(args, graph: dict) -> dict:
    """改写 ACE-Step 1.5 工作流。"""
    tags = args.style
    if not args.lyrics:
        tags += "，纯音乐，无人声，instrumental, no vocals"
    # 94 = TextEncodeAceStepAudio1.5
    e = graph["94"]["inputs"]
    e["tags"] = tags
    e["lyrics"] = args.lyrics
    e["seed"] = args.seed
    e["duration"] = float(args.duration)
    e["bpm"] = args.bpm
    e["timesignature"] = str(args.timesig)
    e["language"] = args.lang
    e["keyscale"] = args.key
    # 3 = KSampler（seed 要与文本编码一致，否则不可复现）
    graph["3"]["inputs"]["seed"] = args.seed
    # 98 = EmptyAceStep1.5LatentAudio
    graph["98"]["inputs"]["seconds"] = float(args.duration)
    # 107 = SaveAudioMP3, 109 = SaveAudioAdvanced(flac)
    keep = "107" if args.format == "mp3" else "109"
    drop = "109" if args.format == "mp3" else "107"
    graph.pop(drop, None)
    graph[keep]["inputs"]["filename_prefix"] = "audio/text2music_ace"
    return graph


def build_yue2(args, graph: dict) -> dict:
    """改写 YuE2 工作流。"""
    style = args.style
    if not args.lyrics:
        style += "｜纯音乐，无人声，instrumental, no vocals"
    graph["54"]["inputs"]["value"] = style          # style
    graph["55"]["inputs"]["value"] = args.lyrics    # lyrics
    graph["53"]["inputs"]["seed"] = args.seed       # SeedNode
    graph["46"]["inputs"]["max_duration"] = float(args.duration)  # YuE2GenerateMusic
    graph["42"]["inputs"]["mode"] = args.mode
    graph["46"]["inputs"]["mode"] = args.mode
    # 10 = 保存节点；mp3 时换成 SaveAudioMP3，flac 时保持 SaveAudioAdvanced
    if args.format == "mp3":
        graph["10"] = {
            "inputs": {
                "filename_prefix": "audio/text2music_yue2",
                "quality": "V0",
                "audio": ["52", 0],
            },
            "class_type": "SaveAudioMP3",
            "_meta": {"title": "保存音频 (MP3)"},
        }
    else:
        graph["10"]["inputs"]["filename_prefix"] = "audio/text2music_yue2"
        graph["10"]["inputs"]["format"] = "flac"
    return graph


def find_audio(history_entry: dict, want_ext: str):
    """在 history 的 outputs 里找音频文件描述，优先匹配目标格式。"""
    outputs = history_entry.get("outputs") or {}
    candidates = []
    for _node_id, out in outputs.items():
        for _key, val in out.items():
            if not isinstance(val, list):
                continue
            for item in val:
                if isinstance(item, dict) and "filename" in item:
                    fn = str(item["filename"]).lower()
                    if fn.endswith(AUDIO_EXT):
                        candidates.append(item)
    if not candidates:
        return None
    for c in candidates:
        if str(c["filename"]).lower().endswith(want_ext):
            return c
    return candidates[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Text2Music via ComfyUI (ACE-Step 1.5 / YuE2)")
    ap.add_argument("--engine", choices=["ace", "yue2"], default="ace")
    ap.add_argument("--style", required=True, help="音乐风格 / 氛围 / 配器描述")
    ap.add_argument("--lyrics", default="", help="歌词（带【主歌】【副歌】等段落标签）；留空=纯音乐")
    ap.add_argument("--lyrics-file", default=None, help="从 UTF-8 文件读取歌词，优先于 --lyrics")
    ap.add_argument("--duration", type=float, default=60.0, help="时长秒，默认 60；完整歌曲用 180~240")
    ap.add_argument("--bpm", type=int, default=120, help="仅 ACE")
    ap.add_argument("--key", default="C major", help="调性，如 'E minor'（仅 ACE）")
    ap.add_argument("--lang", default="zh", help="歌词语言代码（仅 ACE），如 zh/en/ja/yue")
    ap.add_argument("--timesig", default="4", help="拍号 2/3/4/6（仅 ACE）")
    ap.add_argument("--mode", choices=["full", "melody"], default="full", help="仅 YuE2")
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--format", choices=["mp3", "flac"], default="mp3")
    ap.add_argument("--out", default=None, help="本地输出路径")
    ap.add_argument("--host", default=os.environ.get("COMFY_HOST", DEFAULT_HOST))
    ap.add_argument("--timeout", type=int, default=1800, help="轮询超时秒数，默认 1800")
    ap.add_argument("--dry-run", action="store_true", help="只打印改写后的工作流，不提交")
    args = ap.parse_args()

    if args.lyrics_file:
        with open(args.lyrics_file, "r", encoding="utf-8") as f:
            args.lyrics = f.read()

    graph = load_graph(args.engine)
    graph = build_ace(args, graph) if args.engine == "ace" else build_yue2(args, graph)

    if args.dry_run:
        print(json.dumps(graph, ensure_ascii=False, indent=2))
        return 0

    host = args.host.rstrip("/")

    # 1. 探活 + 看队列
    try:
        stats = http_json(f"{host}/system_stats")
    except Exception as e:
        print(f"[ERROR] 连不上 ComfyUI {host}: {e}", file=sys.stderr)
        return 2
    gpu = (stats.get("devices") or [{}])[0].get("name", "?")
    print(f"[OK] ComfyUI 在线：{gpu}")
    try:
        q = http_json(f"{host}/queue")
        running = len(q.get("queue_running") or [])
        pending = len(q.get("queue_pending") or [])
        if running or pending:
            print(f"[WARN] 队列中已有任务 running={running} pending={pending}，本次会排队等待")
    except Exception:
        pass

    # 2. 提交
    client_id = str(uuid.uuid4())
    t0 = time.time()
    print(f"[OK] 提交 {args.engine} / {args.duration}s / seed={args.seed} / {args.format}")
    try:
        res = http_json(f"{host}/prompt", {"prompt": graph, "client_id": client_id})
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:3000]
        print(f"[ERROR] 提交失败 HTTP {e.code}: {detail}", file=sys.stderr)
        return 3
    prompt_id = res.get("prompt_id")
    if not prompt_id:
        print(f"[ERROR] 提交未返回 prompt_id: {res}", file=sys.stderr)
        return 3
    print(f"[OK] prompt_id={prompt_id}")

    # 3. 轮询 history
    entry = None
    last = 0
    while time.time() - t0 < args.timeout:
        time.sleep(5)
        try:
            hist = http_json(f"{host}/history/{prompt_id}")
        except Exception:
            continue
        got = hist.get(prompt_id)
        if got:
            entry = got
            break
        elapsed = int(time.time() - t0)
        if elapsed - last >= 60:
            print(f"[..] 生成中 {elapsed}s")
            last = elapsed
    if entry is None:
        print(f"[ERROR] 超时 {args.timeout}s，prompt_id={prompt_id}", file=sys.stderr)
        return 4

    status = (entry.get("status") or {}).get("status_str", "")
    if status == "error":
        for m in (entry.get("status") or {}).get("messages") or []:
            print(m, file=sys.stderr)
        print(f"[ERROR] 工作流执行失败: {status}", file=sys.stderr)
        return 5

    audio = find_audio(entry, "." + args.format)
    if not audio:
        print(f"[ERROR] history 里没找到音频输出: {json.dumps(entry, ensure_ascii=False)[:2000]}", file=sys.stderr)
        return 6

    # 4. 下载（输出目录是 UNC 网络路径，必须走 /view）
    url = f"{host}/view?" + urllib.parse.urlencode({
        "filename": audio["filename"],
        "subfolder": audio.get("subfolder", ""),
        "type": audio.get("type", "output"),
    })
    data = http_bytes(url)
    ext = os.path.splitext(audio["filename"])[1] or ("." + args.format)
    out = args.out or os.path.abspath(
        f"music_{args.engine}_{int(time.time())}{ext}"
    )
    if not os.path.splitext(out)[1]:
        out += ext
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)

    print(f"[DONE] {out}  ({len(data)/1024/1024:.2f} MB, {time.time()-t0:.1f}s)")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

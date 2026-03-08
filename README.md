# ima bridge (official web, background mode)

This project keeps official ima AI and routes questions through `ima.qq.com` using Playwright persistent profile.

Scope of this version:

- Windows only
- Web driver as default (`--driver web`)
- Legacy app driver (`--driver app`) is deprecated and kept only for compatibility
- Single request per instance (no in-instance concurrency)
- Background mode by default (`headless`)
- First login is manual once, then profile is reused
- Same KB lock: `name=爱分享`, `owner=购物小助手`, `title=【爱分享】的财经资讯`

## Setup

```powershell
conda env create -f environment.yml
conda activate ima
python -m pip install -e .[dev]
python -m playwright install chromium
```

## CLI

```powershell
python -m ima_bridge health
python -m ima_bridge login --timeout 180
python -m ima_bridge ask --question "请用一句话概括今天重点。"
python -m ima_bridge start
```

If no `--question` is provided, a default smoke question is used.

First-time login flow:

```powershell
python -m ima_bridge --driver web login --timeout 180
```

If you need visible browser during `ask`:

```powershell
python -m ima_bridge --driver web --headed ask --question "特斯拉机器人供应商有哪些？"
```

## Startup Program (recommended)

One command startup (auto health check + auto login flow + interactive ask):

```powershell
python -m ima_bridge --driver web start
```

Or use the Windows launcher:

```powershell
.\start_ima_bridge.bat
```

Startup behavior:

- Runs `health`
- If login is required, runs `login` automatically (headed) once
- Remembers the last confirmed KB URL and auto-jumps there next start
- After ready, enters interactive mode (`ima>`)
- Type `:health` to re-check, type `exit` to quit

Multi-instance examples:

```powershell
python -m ima_bridge --instance win1 --driver web login
python -m ima_bridge --instance win1 ask --question "特斯拉机器人供应商有哪些？"
python -m ima_bridge --instance win2 ask --question "长鑫存储上市设备敞口最大是谁？"
```

## Important env vars

- `IMA_DRIVER_MODE`: `web` (default) or `app`
- `IMA_WEB_BASE_URL`: default `https://ima.qq.com/`
- `IMA_WEB_CHANNEL`: default `msedge`
- `IMA_WEB_HEADLESS`: `1` by default
- `IMA_WEB_PROFILE_DIR`: override profile directory
- `IMA_WEB_PROFILE_ROOT`: profile root for multi-instance
- `IMA_ASK_TIMEOUT_SECONDS`: max wait for response completion
- `IMA_CAPTURE_SCREENSHOT`: `0` by default (set `1` to enable screenshots)

Legacy app CDP vars are still available, but the `app` driver path is deprecated and no longer recommended for new setups.

## Python API

Recommended import:

```python
from ima_bridge.service import IMAAskService
```

Legacy compatibility import still works:

```python
from ima_bridge import IMAAskService
```

## Output schema (`ask`)

- `ok`
- `question`
- `knowledge_base`
- `mode`
- `model`
- `source_driver`
- `answer_text`
- `answer_html`
- `references`
- `screenshot_path`
- `captured_at`
- `error_code`
- `error_message`

Standard `error_code` values:

- `KB_NOT_FOUND`
- `CONFIG_MISMATCH`
- `LOGIN_REQUIRED`
- `ASK_TIMEOUT`
- `CAPTURE_FAILED`

## Local chat UI

You can run a local web chat page for normal Q&A:

```powershell
python -m ima_bridge --driver web ui
```

Custom host/port:

```powershell
python -m ima_bridge --driver web ui --host 127.0.0.1 --ui-port 8765
```

UI features:

- Send questions directly to official ima AI
- Stream assistant text output during generation (`/api/ask-stream`)
- Render final `answer_html` in an iframe for richer tables/images/diagrams
- Keep status surface minimal (health + login only)
- Screenshot capture is disabled by default

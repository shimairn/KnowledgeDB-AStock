# ima bridge (app-only, single-thread)

This project keeps the official `ima.copilot` AI workflow and sends questions to the app via CDP.

Scope of this version:

- Windows only
- App driver only (no web fallback)
- Single request per instance (no in-instance concurrency)
- Multi-instance supported (multiple windows/profiles/ports)
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
python -m ima_bridge ask --question "请用一句话概括今天重点。"
```

If no `--question` is provided, a default smoke question is used.

Multi-instance examples:

```powershell
python -m ima_bridge --instance win1 health
python -m ima_bridge --instance win2 --port 9230 health
python -m ima_bridge --instance win2 ask --question "特斯拉机器人供应商有哪些？"
```

## Important env vars

- `IMA_APP_EXECUTABLE`: path to `ima.copilot.exe` (optional if auto-detected)
- `IMA_APP_CDP_PORT`: CDP port, default `9228`
- `IMA_APP_CDP_BASE_PORT`: base port for auto-derived instance ports
- `IMA_MANAGED_PROFILE_DIR`: dedicated automation profile dir
- `IMA_MANAGED_PROFILE_ROOT`: root dir for per-instance profiles
- `IMA_ASK_TIMEOUT_SECONDS`: max wait for response completion

The bridge starts a dedicated app instance with:

- `--remote-debugging-port=<port>`
- `--user-data-dir=<managed_profile>`

It should run without keyboard/mouse foreground takeover.

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

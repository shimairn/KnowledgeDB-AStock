# ima 爱分享知识库桥接

这是一个仅支持 Windows 的 Python 项目，用来把 `ima` 的 `【爱分享】的财经资讯` 知识库桥接为：

- 单次烟测 CLI
- 本地 HTTP API

## 当前行为

- 固定知识库：`爱分享`
- 固定 owner：`购物小助手`
- 固定标题：`【爱分享】的财经资讯`
- 固定模式：`对话模式`
- 固定模型：`DS V3.2`
- 优先尝试检测当前 `ima.copilot` App 窗口
- 如果 App 路径无法满足 HTML 抓取，则自动切换到 Edge 网页端

## 环境准备

已按项目规划创建 conda 环境：

```powershell
conda activate ima
```

如果你要在别的机器复现：

```powershell
conda env create -f environment.yml
conda activate ima
```

## 安装项目

```powershell
conda activate ima
python -m pip install -e .
```

## 运行烟测

默认问题：`请概括这个知识库的主要栏目，并说明各自关注点。`

```powershell
conda activate ima
python -m ima_bridge
```

自定义问题：

```powershell
conda activate ima
python -m ima_bridge --question "请总结最近值得关注的栏目重点"
```

首次走网页兜底时，程序会打开 Edge 持久化 profile。若未登录，会等待你手动扫码登录 `ima`。

## 启动本地 API

```powershell
conda activate ima
python -m ima_bridge serve --host 127.0.0.1 --port 8000
```

### `GET /health`

返回 app/web driver 可用性。

### `POST /ask`

请求体：

```json
{ "question": "请概括这个知识库的主要栏目，并说明各自关注点。" }
```

成功响应会包含：

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

失败时会返回：

- `error_code`
- `error_message`

## 输出目录

运行期产物都放在未跟踪目录：

- `output/playwright/profiles/msedge/`：Edge 持久化登录态
- `output/playwright/screenshots/`：回答截图与诊断截图

## 说明

- `app` driver 当前实现为“检测 + 预检 + 诊断截图”。如果无法稳定拿到回答区 HTML，会自动回退到网页端。
- 网页端 driver 会尽量用文本选择器和可见控件来定位知识库、模式、模型和输入框。

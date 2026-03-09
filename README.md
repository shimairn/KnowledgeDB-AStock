# ima-bridge

`ima-bridge` 通过 Playwright 复用官方 `ima.qq.com` Web Profile，把固定知识库问答能力包装成可部署的单机多 worker 服务。

当前版本重点：

- Windows 环境
- 默认 `web` 驱动
- 单机多 worker 并发
- 匿名公网访问
- 单个 FastAPI 进程同时提供静态前端与 API
- `app` 驱动仅保留 CLI 兼容，不参与公网 `ui`

## 安装

```powershell
conda env create -f environment.yml
conda activate ima
python -m pip install -e .[dev]
python -m playwright install chromium
```

## 常用命令

```powershell
python -m ima_bridge health
python -m ima_bridge login --timeout 180
python -m ima_bridge ask --question "请用一句话介绍这个知识库。"
python -m ima_bridge start
```

## 并发公网模式

首次部署前，先初始化全部 worker 的 Playwright profile：

```powershell
python -m ima_bridge login-pool --workers 10
```

然后启动匿名公网服务：

```powershell
python -m ima_bridge ui --host 0.0.0.0 --ui-port 8765 --workers 10
```

建议在服务前面加 HTTPS 反向代理，并使用同域反代把静态页面与 `/api/*` 汇到同一个域名。

## UI 行为

- 打开页面即可提问，无需登录
- 前端先调用 `/api/ui-config` 与 `/api/health`
- `/api/ask-stream` 维持 `start -> thinking_delta* -> answer_html* -> done`
- 正文始终通过 iframe `srcdoc` 渲染，不再回退到正文纯文本流
- UI 为单主区对话布局，保留输入区模型切换与新建对话
- 思考过程独立折叠显示，不进入正文富文本
- 不展示知识库来源 chips、原文预览抽屉或检索命中数提示
- worker 满载时返回 `429 BUSY`
- 单 IP 超过限流阈值时返回 `429 RATE_LIMITED`

## 运维说明

- `login-pool` 是管理员初始化 worker profile 的命令，不是终端用户登录
- 若某个 worker 登录态失效，健康接口会反映为 `login_required`
- 仍可继续使用其余 `ready` worker 提供服务

## 重要环境变量

- `IMA_DRIVER_MODE`：默认 `web`
- `IMA_WEB_HEADLESS`：默认 `1`
- `IMA_WEB_PROFILE_ROOT`：多实例 Web Profile 根目录
- `IMA_UI_WORKER_COUNT`：默认 `10`
- `IMA_UI_RATE_LIMIT_PER_MINUTE`：默认 `12`
- `IMA_UI_MAX_CONCURRENT_PER_IP`：默认 `2`
- `IMA_UI_TRUST_PROXY`：默认 `0`，设为 `1` 时信任 `X-Forwarded-For`

## Python API

推荐导入：

```python
from ima_bridge.service import IMAAskService
```

兼容导入仍可使用：

```python
from ima_bridge import IMAAskService
```

## 测试

统一在 `ima` 环境执行：

```powershell
conda run --no-capture-output -n ima python -m pytest -q
```



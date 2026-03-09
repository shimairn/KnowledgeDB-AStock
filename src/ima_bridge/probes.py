from __future__ import annotations

CONTENT_PREFIX = "内容("
INPUT_HINT = "输入#"

LOGIN_HINTS = (
    "扫码",
    "微信登录",
    "登录后",
    "请先登录",
    "立即登录",
    "登录一下",
    "登录以同步历史会话",
    "即可开启你的专属知识库",
    "即可查看你的历史",
)

LOADING_HINTS = (
    "思考中",
    "生成中",
    "回答中",
    "加载中",
    "正在搜索知识库资料",
    "停止回答",
)

MIN_TARGET_SCORE = 4
GENERIC_TARGET_URL_PATHS = {"", "/", "/wikis"}

KB_NAV_TEXTS = ("我的知识库", "我加入的")

COMPOSER_SELECTORS = (
    "textarea[placeholder*='输入#']",
    "textarea[placeholder*='输入']",
    "textarea",
    "[contenteditable='true']",
)

APP_COMPOSER_SELECTORS = (
    "textarea[placeholder*='输入#']",
    "textarea",
    "[contenteditable='true']",
)

SEND_CONTROL_SELECTORS = (
    "#chat-input-bar-id span.icon-send-enable-big",
    "#chat-input-bar-id span[class*='icon-send-enable']",
    "#chat-input-bar-id [class*='sendBtnWrap'] span",
    "#chat-input-bar-id [class*='sendBtnWrap']",
)

MODEL_TRIGGER_SELECTORS = (
    "div[class*='_modelWrap_'] div[class*='_currentChoiceWrap_']",
    "div[class*='_currentChoiceWrap_']",
    "div[class*='_modelWrap_']",
)

MODEL_TITLE_SELECTORS = (
    "div[class*='_title_']",
    "[class*='_title_']",
)

MODEL_OPTION_SELECTOR = "div[class*='_modelOption_']"
MODEL_OPTION_NAME_SELECTOR = "div[class*='_name_']"
MODEL_OPTION_DESC_SELECTOR = "div[class*='_desc_']"
MODEL_OPTION_SELECTED_HINT = "_selected_"

AI_CONTAINER_SELECTORS = (
    "div[class*='normalModeAiBubbleWrapper'] div[class*='aiContainer']",
    "div[class*='aiContainer_']",
)

AI_BUBBLE_SELECTOR = "div[class*='_bubble_']"

APP_DRIVER_DEPRECATION_MESSAGE = (
    "--driver app is deprecated and kept only as a legacy compatibility path; prefer --driver web."
)

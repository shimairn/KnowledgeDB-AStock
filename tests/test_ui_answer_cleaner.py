from __future__ import annotations

from ima_bridge.ui_answer_cleaner import clean_answer_html, clean_answer_payload, clean_answer_text


def test_clean_answer_text_removes_short_retrieval_noise_lines():
    raw = "找到 12 条知识库内容\n\n这是正式回答。"

    assert clean_answer_text(raw) == "这是正式回答。"


def test_clean_answer_text_keeps_normal_numbers_and_tables():
    raw = "2024 年营收为 12.5 亿元。\n\n| 项目 | 数值 |\n| --- | --- |\n| 命中数 | 3 |"
    cleaned = clean_answer_text(raw)

    assert "12.5" in cleaned
    assert "| 命中数 | 3 |" in cleaned


def test_clean_answer_html_removes_noise_blocks_but_keeps_quotes_and_tables():
    raw = "<p>找到 3 条知识库内容</p><p>正式回答</p><table><tr><td>3</td></tr></table><blockquote>引用 2 条规则</blockquote>"
    cleaned = clean_answer_html(raw)

    assert "找到 3 条知识库内容" not in cleaned
    assert "<p>正式回答</p>" in cleaned
    assert "<table>" in cleaned
    assert "<blockquote>" in cleaned


def test_clean_answer_html_removes_thinking_and_source_wrappers():
    raw = (
        '<details class="thinking-panel"><summary>思考过程</summary><div>这里是思考</div></details>'
        '<section data-role="source-list"><a href="https://example.com">打开原文</a></section>'
        "<p>最终答案</p>"
    )
    cleaned = clean_answer_html(raw)

    assert "思考过程" not in cleaned
    assert "打开原文" not in cleaned
    assert "<p>最终答案</p>" in cleaned


def test_clean_answer_html_removes_brand_icons_and_charts():
    raw = (
        '<div class="ima-logo"><img src="https://example.com/logo.png" alt="ima logo" width="24" height="24" /></div>'
        '<figure class="chart-panel"><svg><rect width="10" height="10" /></svg></figure>'
        "<p>答案正文</p>"
    )
    cleaned = clean_answer_html(raw)

    assert "ima-logo" not in cleaned
    assert "<svg" not in cleaned
    assert "答案正文" in cleaned


def test_clean_answer_html_keeps_regular_content_images():
    raw = '<figure><img src="https://example.com/etcher.jpg" alt="刻蚀设备示意图" width="640" height="360" /></figure>'
    cleaned = clean_answer_html(raw)

    assert "etcher.jpg" in cleaned
    assert "刻蚀设备示意图" in cleaned


def test_clean_answer_html_keeps_images_even_if_class_contains_ima():
    raw = '<figure><img class="ima-chart" src="https://example.com/chart.png" alt="走势图" /></figure>'
    cleaned = clean_answer_html(raw)

    assert "chart.png" in cleaned
    assert "走势图" in cleaned


def test_clean_answer_html_removes_file_reference_blocks_and_inline_indexes():
    raw = (
        '<div class="pageListWrap">'
        '<div><li>1.半导体设备行业深度报告.pdf</li></div>'
        '<div><li>2.先进封装月报.pdf</li></div>'
        '<div id="@context-ref?id=1">1</div>'
        '</div>'
        '<p>正式答案</p>'
    )
    cleaned = clean_answer_html(raw)

    assert "行业深度报告.pdf" not in cleaned
    assert "@context-ref" not in cleaned
    assert "<p>正式答案</p>" in cleaned


def test_clean_answer_payload_updates_text_and_html_together():
    cleaned = clean_answer_payload(
        {
            "answer_text": "已为你找到 2 条相关内容\n\n答案正文",
            "answer_html": "<div>已为你找到 2 条相关内容</div><p>答案正文</p>",
        }
    )

    assert cleaned["answer_text"] == "答案正文"
    assert "已为你找到 2 条相关内容" not in cleaned["answer_html"]
    assert "答案正文" in cleaned["answer_html"]
def test_clean_answer_html_removes_leading_plain_text_block_before_markdown_answer():
    raw = (
        '<div class="_message_fymew_1">\u597d\u7684\uff0c\u7528\u6237\u518d\u6b21\u8981\u6c42\u5355\u4e3b\u533a\u5bf9\u8bdd\u6536\u655b\uff0c'
        '\u9700\u8981\u628a\u601d\u8003\u4e0e\u6b63\u6587\u5f7b\u5e95\u5206\u79bb\u3002</div>'
        '<div class="_markdown_60wa1_1"><p>\u534a\u5bfc\u4f53\u8bbe\u5907\u4e3b\u8981\u5305\u62ec\u5149\u523b\u3001'
        '\u523b\u8680\u3001\u6c89\u79ef\u4e0e\u68c0\u6d4b\u8bbe\u5907\u3002</p></div>'
    )

    cleaned = clean_answer_html(raw)

    assert "\u7528\u6237\u518d\u6b21\u8981\u6c42" not in cleaned
    assert "_markdown_60wa1_1" in cleaned
    assert "\u534a\u5bfc\u4f53\u8bbe\u5907" in cleaned

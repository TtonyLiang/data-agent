import json

from app.main import compact_json_text, compact_report_payload_text


def test_compact_json_text_preserves_valid_json_when_truncated():
    payload = json.dumps([{"id": idx, "value": "x" * 50} for idx in range(200)])

    compacted = compact_json_text(payload, 500)

    assert isinstance(json.loads(compacted), dict)


def test_compact_report_payload_text_preserves_valid_json_when_truncated():
    payload = json.dumps(
        {
            "title": "报告",
            "markdown": "正文" * 10000,
            "sections": [{"title": str(idx), "body": "x" * 1000} for idx in range(100)],
        },
        ensure_ascii=False,
    )

    compacted = compact_report_payload_text(payload, 1200)
    parsed = json.loads(compacted)

    assert parsed["truncated"] is True

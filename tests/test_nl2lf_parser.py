from app.agent.nodes.nl2lf_generate import parse_logic_form


def test_parse_logic_form_normalizes_empty_object_slots():
    logic_form = parse_logic_form(
        '{"metrics": ["application_count"], "dimensions": [], "filters": {}, "sort": {}}'
    )

    assert logic_form.filters == []
    assert logic_form.sort == []

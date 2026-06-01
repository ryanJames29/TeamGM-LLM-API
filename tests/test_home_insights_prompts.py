from app.prompts.home_insights import HOME_INSIGHT_SECTIONS, build_system_prompt


def test_build_system_prompt_includes_every_section():
    prompt = build_system_prompt()

    assert "upcomingGame" not in prompt

    for section in HOME_INSIGHT_SECTIONS:
        assert f"## {section.key}" in prompt
        assert section.instructions in prompt

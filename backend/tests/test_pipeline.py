"""Tests for video generation pipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.script_generator import ScriptGenerator, EpisodeScript, SceneScript
from app.services.video_generator import VideoGenerator, VideoClip


class TestScriptGenerator:
    """Tests for script generation service."""

    @pytest.fixture
    def mock_anthropic_response(self):
        """Mock Anthropic API response."""
        return MagicMock(
            content=[MagicMock(text='{"title": "Test Episode", "scenes": []}')],
            usage=MagicMock(input_tokens=100, output_tokens=200),
        )

    def test_build_prompt(self):
        """Test prompt building."""
        generator = ScriptGenerator()
        characters = [
            {"name": "max", "personality": "competitive", "voice_description": "Dutch"},
        ]
        prompt = generator._build_prompt(
            race_context="Test race context",
            characters=characters,
            episode_type="post-race",
        )
        assert "max" in prompt
        assert "competitive" in prompt
        assert "post-race" in prompt

    def test_calculate_cost(self):
        """Test cost calculation."""
        generator = ScriptGenerator()
        cost = generator._calculate_cost(input_tokens=1000, output_tokens=1000)
        # Haiku: $0.25/1M input, $1.25/1M output
        expected = (1000 / 1000) * 0.00025 + (1000 / 1000) * 0.00125
        assert cost == pytest.approx(expected)

    def test_parse_response_with_code_block(self):
        """Test parsing response with markdown code block."""
        generator = ScriptGenerator()
        content = '```json\n{"title": "Test", "scenes": []}\n```'
        result = generator._parse_response(content)
        assert result["title"] == "Test"


class TestVideoGenerator:
    """Tests for video generation service."""

    def test_build_prompt_with_all_fields(self):
        """Test prompt building with all fields."""
        generator = VideoGenerator()
        prompt = generator._build_prompt(
            action="Character waves",
            dialogue="Hello world",
            audio_description="Crowd noise",
        )
        assert "Character waves" in prompt
        assert "<S>Hello world<E>" in prompt
        assert "<AUDCAP>Crowd noise<ENDAUDCAP>" in prompt

    def test_build_prompt_without_optional(self):
        """Test prompt building without optional fields."""
        generator = VideoGenerator()
        prompt = generator._build_prompt(action="Character waves")
        assert "Character waves" in prompt
        assert "<S>" not in prompt
        assert "<AUDCAP>" not in prompt

    def test_build_prompt_with_dialogue_only(self):
        """Test prompt with dialogue but no audio."""
        generator = VideoGenerator()
        prompt = generator._build_prompt(
            action="Speaking",
            dialogue="Test dialogue",
        )
        assert "<S>Test dialogue<E>" in prompt
        assert "<AUDCAP>" not in prompt


class TestIntegration:
    """Integration tests (requires mocking external services)."""

    @pytest.mark.asyncio
    async def test_script_to_scenes(self):
        """Test converting script to scene objects."""
        scenes_data = [
            {
                "scene_number": 1,
                "character": "max",
                "action": "waves",
                "dialogue": "Hello",
                "audio_description": "crowd noise",
            },
            {
                "scene_number": 2,
                "character": "lewis",
                "action": "nods",
                "dialogue": "Indeed",
                "audio_description": "studio",
            },
        ]

        scenes = [
            SceneScript(
                scene_number=s["scene_number"],
                character=s["character"],
                action=s["action"],
                dialogue=s.get("dialogue"),
                audio_description=s.get("audio_description"),
            )
            for s in scenes_data
        ]

        assert len(scenes) == 2
        assert scenes[0].scene_number == 1
        assert scenes[1].character == "lewis"

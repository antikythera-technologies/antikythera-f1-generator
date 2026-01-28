"""API endpoint tests."""

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client: TestClient):
        """Test health check returns healthy."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_root_endpoint(self, client: TestClient):
        """Test root endpoint returns app info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Antikythera F1 Video Generator"
        assert "version" in data


class TestCharactersAPI:
    """Tests for characters API."""

    def test_list_characters_empty(self, client: TestClient):
        """Test listing characters when empty."""
        response = client.get("/api/v1/characters")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_character(self, client: TestClient):
        """Test creating a character."""
        character_data = {
            "name": "max_verstappen",
            "display_name": "Max Verstappen",
            "description": "Dutch racing driver",
            "voice_description": "Dutch accent, confident",
            "personality": "Competitive, direct",
        }
        response = client.post("/api/v1/characters", json=character_data)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "max_verstappen"
        assert data["display_name"] == "Max Verstappen"
        assert "id" in data


class TestRacesAPI:
    """Tests for races API."""

    def test_list_races_empty(self, client: TestClient):
        """Test listing races when empty."""
        response = client.get("/api/v1/races")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_race(self, client: TestClient):
        """Test creating a race."""
        race_data = {
            "season": 2025,
            "round_number": 1,
            "race_name": "Bahrain Grand Prix",
            "circuit_name": "Bahrain International Circuit",
            "country": "Bahrain",
            "race_date": "2025-03-02",
        }
        response = client.post("/api/v1/races", json=race_data)
        assert response.status_code == 200
        data = response.json()
        assert data["race_name"] == "Bahrain Grand Prix"
        assert data["season"] == 2025


class TestEpisodesAPI:
    """Tests for episodes API."""

    def test_list_episodes_empty(self, client: TestClient):
        """Test listing episodes when empty."""
        response = client.get("/api/v1/episodes")
        assert response.status_code == 200
        assert response.json() == []

    def test_generate_episode_race_not_found(self, client: TestClient):
        """Test generating episode for non-existent race."""
        request_data = {
            "race_id": 999,
            "episode_type": "post-race",
        }
        response = client.post("/api/v1/episodes/generate", json=request_data)
        assert response.status_code == 404
        assert "Race not found" in response.json()["detail"]


class TestAnalyticsAPI:
    """Tests for analytics API."""

    def test_get_costs(self, client: TestClient):
        """Test getting cost analytics."""
        response = client.get("/api/v1/analytics/costs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_performance(self, client: TestClient):
        """Test getting performance metrics."""
        response = client.get("/api/v1/analytics/performance")
        assert response.status_code == 200
        data = response.json()
        assert "total_episodes" in data
        assert "success_rate" in data

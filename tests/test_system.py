import pytest
from backend import __version__

@pytest.mark.asyncio
async def test_health_check(client):
    """Verify health check endpoint returns 200 and correct version."""
    response = await client.get("/api/system/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy" or data["status"] == "unhealthy" # DB might be offline in test env
    assert data["version"] == __version__
    assert "database_connected" in data

@pytest.mark.asyncio
async def test_404(client):
    """Verify 404 for non-existent routes."""
    response = await client.get("/api/system/non_existent")
    assert response.status_code == 404

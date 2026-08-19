from openjarvis.server.spa_fallback import (
    backend_not_found_response,
    is_backend_path,
)


def test_backend_namespaces_never_fall_back_to_spa() -> None:
    assert is_backend_path("v1/missing") is True
    assert is_backend_path("/edge/missing") is True
    assert is_backend_path("health") is True
    assert is_backend_path("webhooks/provider") is True


def test_frontend_routes_remain_eligible_for_spa_fallback() -> None:
    assert is_backend_path("") is False
    assert is_backend_path("jarvis") is False
    assert is_backend_path("settings/integrations") is False


def test_backend_not_found_uses_stable_public_envelope() -> None:
    response = backend_not_found_response()

    assert response.status_code == 404
    assert response.body == (
        b'{"error":{"code":"route_not_found",'
        b'"message":"Backend route not found."}}'
    )

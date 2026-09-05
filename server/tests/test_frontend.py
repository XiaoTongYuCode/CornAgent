def test_frontend_routes_support_direct_navigation_and_assets(settings, client_factory, tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    index = '<!doctype html><div id="root"></div>'
    (dist / "index.html").write_text(index)
    (assets / "app.js").write_text("export {};")
    settings.frontend_dist = dist

    with client_factory() as client:
        for route in ("/", "/chat", "/chat/example-session", "/sidebar", "/rendering"):
            response = client.get(route)
            assert response.status_code == 200
            assert response.text == index
            assert response.headers["cache-control"] == "no-cache"
        assert client.get("/assets/app.js").text == "export {};"
        assert client.get("/api/nonexistent").status_code == 404

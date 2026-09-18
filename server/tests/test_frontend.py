def test_frontend_routes_support_direct_navigation_and_assets(settings, client_factory, tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    index = '<!doctype html><div id="root"></div>'
    (dist / "index.html").write_text(index)
    (assets / "app.js").write_text("export {};")
    settings.frontend_dist = dist

    with client_factory() as client:
        for route in (
            "/", "/chat", "/chat/example-session", "/sidebar", "/rendering", "/usage", "/profile"
        ):
            response = client.get(route)
            assert response.status_code == 200
            assert response.text == index
            assert response.headers["cache-control"] == "no-cache"
        assert client.get("/assets/app.js").text == "export {};"
        assert client.get("/api/nonexistent").status_code == 404


def test_search_documents_and_private_pages_have_separate_responses(
    settings, client_factory, tmp_path, monkeypatch
):
    # OS MIME databases differ; discovery documents must use the same types everywhere.
    monkeypatch.setattr("mimetypes.guess_type", lambda *_args, **_kwargs: ("text/xml", None))
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<title>CornAgent</title><h1>Open-source AI agent</h1>')
    (dist / "app.html").write_text('<meta name="robots" content="noindex, follow">')
    for route in ("sidebar", "rendering", "usage", "profile"):
        (dist / f"{route}.html").write_text(f'<title>{route}</title>')
    documents = {
        "robots.txt": ("text/plain", "User-agent: *\nAllow: /\n"),
        "sitemap.xml": ("application/xml", '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'),
        "llms.txt": ("text/plain", "# CornAgent\n"),
        "favicon.svg": ("image/svg+xml", '<svg xmlns="http://www.w3.org/2000/svg"/>'),
        ".well-known/aiagentslisting-verify.txt": (
            "text/plain", "6b9fe50fb649b08fbc102eb3ee2532ae"
        ),
    }
    for filename, (_, content) in documents.items():
        (dist / filename).parent.mkdir(parents=True, exist_ok=True)
        (dist / filename).write_text(content)
    (dist / "private.txt").write_text("never served")
    settings.frontend_dist = dist
    with client_factory() as client:
        for route in ("/", "/chat"):
            response = client.get(route)
            assert "Open-source AI agent" in response.text
            assert "x-robots-tag" not in response.headers
        for route in ("/chat/example-session", "/sidebar", "/rendering", "/usage", "/profile"):
            response = client.get(route)
            assert response.status_code == 200
            assert response.headers["x-robots-tag"] == "noindex"
            assert "Open-source AI agent" not in response.text
        for filename, (media_type, content) in documents.items():
            response = client.get(f"/{filename}")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(media_type)
            assert response.text == content
        assert client.get("/api/nonexistent").headers["x-robots-tag"] == "noindex"
        assert client.get("/private.txt").status_code == 404
        assert client.get("/missing-page").status_code == 404
        (dist / "sitemap.xml").unlink()
        assert client.get("/sitemap.xml").status_code == 404

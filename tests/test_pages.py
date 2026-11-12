import pytest
from app import create_app
from build_pages import build


def test_pages_build_uses_project_relative_assets_and_external_api(tmp_path):
    build('https://ivrit.example/', tmp_path)
    html = (tmp_path / 'index.html').read_text()
    assert 'content="https://ivrit.example"' in html
    assert 'href="./static/style.css"' in html
    assert 'src="./static/app.js"' in html
    assert 'src="./static/browser-storage.js"' in html
    assert 'data-public="true"' in html
    assert '{{' not in html and '{%' not in html
    assert {p.name for p in tmp_path.iterdir()} == {'index.html', '.nojekyll', 'static'}
    assert 'src="./static/anki-connect.js"' in html
    assert {p.name for p in (tmp_path / 'static').iterdir()} == {'style.css', 'app.js', 'browser-storage.js', 'anki-connect.js'}


@pytest.mark.parametrize('url', ['', 'http://ivrit.example', 'https://ivrit.example/path', 'https://user:secret@ivrit.example', 'https://ivrit.example?x=1'])
def test_pages_rejects_invalid_backend_origin(tmp_path, url):
    with pytest.raises(ValueError):
        build(url, tmp_path)


def test_pages_cors_and_preflight(tmp_path, monkeypatch):
    origin = 'https://schwester-ester.github.io'
    monkeypatch.setenv('IVRIT_ALLOWED_ORIGINS', origin)
    client = create_app(tmp_path / 'public.sqlite3', public=True).test_client()
    headers = {'Origin': origin, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'}
    response = client.options('/api/text', headers=headers)
    assert response.status_code == 204
    assert response.headers['Access-Control-Allow-Origin'] == origin
    assert response.headers['Access-Control-Allow-Headers'] == 'Content-Type'
    response = client.post('/api/text', json={'text': 'ספר'}, headers={'Origin': origin})
    assert response.status_code == 200
    assert response.json['tokens'][0]['key'] == 'ספר'
    assert response.headers['Access-Control-Allow-Origin'] == origin
    response = client.post('/api/manual', json={}, headers={'Origin': origin})
    assert response.status_code == 400
    assert response.headers['Access-Control-Allow-Origin'] == origin
    for method in ('post', 'options'):
        response = getattr(client, method)('/api/text', json={}, headers={'Origin': 'https://evil.example'})
        assert response.status_code == 403
        assert 'Access-Control-Allow-Origin' not in response.headers
    local = create_app(tmp_path / 'local.sqlite3', public=False).test_client()
    assert local.post('/api/text', json={'text': 'ספר'}, headers={'Origin': origin}).status_code == 403

"""Build only the public interface; the Python API runs on a separate host."""
import argparse
from pathlib import Path
import shutil
from urllib.parse import urlsplit
from jinja2 import Environment, FileSystemLoader, select_autoescape


def build(api_base, destination):
    api_base = api_base.rstrip('/')
    url = urlsplit(api_base)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path:
        raise ValueError('Set IVRIT_API_BASE to the HTTPS origin of your deployed Python backend (without a path).')
    root = Path(__file__).resolve().parent
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(root / 'templates'), autoescape=select_autoescape())
    html = env.get_template('index.html').render(public=True, asset_base='./static/', api_base=api_base)
    (destination / 'index.html').write_text(html, encoding='utf-8')
    (destination / '.nojekyll').touch()
    (destination / 'static').mkdir(exist_ok=True)
    for name in ('style.css', 'app.js', 'browser-storage.js', 'anki-connect.js'):
        shutil.copyfile(root / 'static' / name, destination / 'static' / name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-base', required=True)
    parser.add_argument('--output', default='dist')
    args = parser.parse_args()
    build(args.api_base, args.output)

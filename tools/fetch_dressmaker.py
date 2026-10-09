"""Fetch public, official Steam images as local OCR regression fixtures."""
import json
from pathlib import Path
from urllib.parse import urlparse
import httpx
import argparse
import re
import html

parser = argparse.ArgumentParser()
parser.add_argument('--appid', default='4019220')
parser.add_argument('--folder', default='dressmaker')
args = parser.parse_args()
directory = Path('artifacts') / args.folder
directory.mkdir(parents=True, exist_ok=True)
with httpx.Client(timeout=45, follow_redirects=True) as client:
    response = client.get("https://store.steampowered.com/api/appdetails", params={"appids": args.appid, "l": "english"})
    response.raise_for_status()
    result = response.json().get(args.appid, {})
    if result.get('data'):
        data = result['data']
    else:
        page = client.get(f'https://store.steampowered.com/app/{args.appid}/')
        page.raise_for_status()
        match = re.search(r'data-featuretarget="gamehighlight-desktopcarousel"\s+data-props="([^"]+)"', page.text)
        if not match:
            raise ValueError('Official screenshot metadata unavailable')
        props = json.loads(html.unescape(match.group(1)))
        data = {'name': props['appName'], 'screenshots': [{'id': i, 'path_full': s['full']}
            for i, s in enumerate(props['screenshots'])], 'movies': props.get('trailers', [])}
    manifest = {"app_id": args.appid, "name": data["name"], "source": f"https://store.steampowered.com/app/{args.appid}/", "screenshots": [], "movies": data.get("movies", [])}
    for screenshot in data.get("screenshots", []):
        url = screenshot["path_full"]
        host = urlparse(url).hostname or ""
        if not host.endswith("steamstatic.com"):
            raise ValueError("Unexpected screenshot host")
        image = client.get(url)
        image.raise_for_status()
        path = directory / f"steam-{screenshot['id']:02d}.jpg"
        path.write_bytes(image.content)
        manifest["screenshots"].append({"path": path.name, "url": url})
    (directory / "sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"name": data["name"], "screenshots": len(manifest["screenshots"]), "movies": manifest["movies"]}, indent=2))

import re
from urllib.parse import quote, unquote, urljoin
from flask import Flask, Response, jsonify, request
import requests
import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

app = Flask(__name__)

# --- CONFIGURATION EVANGILE TV (Hexaglobe) ---
EVANGILE_API_URL = (
    "https://evangiletv-live1-p-api.hexaglobe.net/"
    "cec61441155731421275087a35fc2d98/1795022284/"
    "evangiletv/EvangileTV-website-web-1/live1/stream_info.php"
)

# --- CONFIGURATION EMCI TV (Dailymotion) ---
EMCI_VIDEO_URL = "https://www.dailymotion.com/video/x8azdkm"

PROFILES = {
    "evangile": {
        "Origin": "https://evangile.tv",
        "Referer": "https://evangile.tv/",
    },
    "emci": {
        "Origin": "https://www.dailymotion.com",
        "Referer": "https://www.dailymotion.com/",
    },
}


def get_headers(profile="evangile", is_api=False):
    p = PROFILES.get(profile, PROFILES["evangile"])
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01" if is_api else "*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": p["Origin"],
        "Referer": p["Referer"],
    }


def extract_m3u8_urls(data):
    urls = []
    if isinstance(data, dict):
        for value in data.values():
            urls.extend(extract_m3u8_urls(value))
    elif isinstance(data, list):
        for item in data:
            urls.extend(extract_m3u8_urls(item))
    elif isinstance(data, str) and ".m3u8" in data:
        clean_url = data.replace("\\/", "/")
        if clean_url.startswith("http"):
            urls.append(clean_url)
    return list(dict.fromkeys(urls))


def get_evangiletv_streams():
    r = requests.get(
        EVANGILE_API_URL, headers=get_headers("evangile", is_api=True), timeout=10
    )
    r.raise_for_status()
    try:
        streams = extract_m3u8_urls(r.json())
    except ValueError:
        raw_text = r.text.replace("\\/", "/")
        streams = list(
            dict.fromkeys(re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', raw_text))
        )
    if not streams:
        raise RuntimeError("Aucune URL .m3u8 trouvée pour EVANGILETV.")
    return streams


def get_emcitv_m3u8():
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best",
        "impersonate": ImpersonateTarget("chrome"),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(EMCI_VIDEO_URL, download=False)
        if info.get("manifest_url"):
            return info["manifest_url"]
        if info.get("url") and ".m3u8" in info["url"]:
            return info["url"]
        for f in reversed(info.get("formats", [])):
            if f.get("protocol") in ("m3u8", "m3u8_native") and f.get("url"):
                return f["url"]
    raise RuntimeError("Impossible d'extraire le flux m3u8 pour EMCITV.")


@app.route("/")
@app.route("/ping")
def index():
    return (
        "Proxy Multi-Chaînes actif. Flux disponibles : "
        "/EVANGILETV.m3u8, /EVANGILETV2.m3u8, /EMCITV.m3u8, /playlist.m3u"
    )


@app.route("/playlist.m3u")
def playlist():
    base_url = request.host_url.rstrip("/")
    lines = [
        "#EXTM3U",
        '#EXTINF:-1 tvg-id="EVANGILETV" tvg-name="EVANGILETV",EVANGILETV',
        f"{base_url}/EVANGILETV.m3u8",
        '#EXTINF:-1 tvg-id="EVANGILETV2" tvg-name="EVANGILETV (Flux 2)",EVANGILETV (Flux 2)',
        f"{base_url}/EVANGILETV2.m3u8",
        '#EXTINF:-1 tvg-id="EMCITV" tvg-name="EMCI TV",EMCI TV',
        f"{base_url}/EMCITV.m3u8",
    ]
    return Response("\n".join(lines) + "\n", mimetype="audio/x-mpegurl")


@app.route("/EVANGILETV.m3u8")
@app.route("/live.m3u8")
def evangiletv_1():
    try:
        streams = get_evangiletv_streams()
        return proxy_m3u8(streams[0], profile="evangile")
    except Exception as e:
        return Response(f"Erreur EVANGILETV : {e}", status=502)


@app.route("/EVANGILETV2.m3u8")
@app.route("/live2.m3u8")
def evangiletv_2():
    try:
        streams = get_evangiletv_streams()
        if len(streams) < 2:
            return Response("Deuxième flux EVANGILETV non disponible.", status=404)
        return proxy_m3u8(streams[1], profile="evangile")
    except Exception as e:
        return Response(f"Erreur EVANGILETV2 : {e}", status=502)


@app.route("/EMCITV.m3u8")
def emcitv():
    try:
        master_url = get_emcitv_m3u8()
        return proxy_m3u8(master_url, profile="emci")
    except Exception as e:
        return Response(f"Erreur EMCITV : {e}", status=502)


@app.route("/proxy")
def proxy():
    target_url = unquote(request.args.get("url", ""))
    profile = request.args.get("p", "evangile")
    if not target_url.startswith("http"):
        return Response("URL invalide", status=400)

    if ".m3u8" in target_url:
        return proxy_m3u8(target_url, profile=profile)

    r = requests.get(
        target_url, headers=get_headers(profile, is_api=False), stream=True, timeout=15
    )
    return Response(
        r.iter_content(chunk_size=32768),
        status=r.status_code,
        content_type=r.headers.get("Content-Type", "video/MP2T"),
    )


def proxy_m3u8(m3u8_url, profile="evangile"):
    r = requests.get(m3u8_url, headers=get_headers(profile, is_api=False), timeout=10)
    r.raise_for_status()
    base_proxy = f"{request.host_url.rstrip('/')}/proxy?p={profile}&url="

    rewritten_lines = []
    for line in r.text.splitlines():
        stripped = line.strip()
        if not stripped:
            rewritten_lines.append(line)
        elif stripped.startswith("#"):
            def replace_uri(match):
                abs_url = urljoin(m3u8_url, match.group(1))
                return f'URI="{base_proxy}{quote(abs_url, safe="")}"'

            rewritten_lines.append(re.sub(r'URI="([^"]+)"', replace_uri, line))
        else:
            abs_url = urljoin(m3u8_url, stripped)
            rewritten_lines.append(f"{base_proxy}{quote(abs_url, safe='')}")

    return Response(
        "\n".join(rewritten_lines), mimetype="application/vnd.apple.mpegurl"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

import re
from urllib.parse import quote, unquote, urljoin
from flask import Flask, Response, jsonify, request
import requests

app = Flask(__name__)

CHANNEL_TITLE = "EVANGILETV"
API_URL = (
    "https://evangiletv-live1-p-api.hexaglobe.net/"
    "cec61441155731421275087a35fc2d98/1795022284/"
    "evangiletv/EvangileTV-website-web-1/live1/stream_info.php"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.evangiletv.com/",
    "Origin": "https://www.evangiletv.com",
    "Accept": "*/*",
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
    r = requests.get(API_URL, headers=HEADERS, timeout=10)
    r.raise_for_status()
    try:
        payload = r.json()
        streams = extract_m3u8_urls(payload)
    except ValueError:
        raw_text = r.text.replace("\\/", "/")
        streams = list(
            dict.fromkeys(re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', raw_text))
        )

    if not streams:
        raise RuntimeError("Aucune URL .m3u8 trouvée dans la réponse stream_info.php.")
    return streams


@app.route("/")
def index():
    return (
        f"{CHANNEL_TITLE} Proxy actif. Routes disponibles : "
        "/EVANGILETV.m3u, /live.m3u8, /live2.m3u8, /debug"
    )


@app.route("/debug")
def debug():
    try:
        streams = get_evangiletv_streams()
        preview = []
        for idx, url in enumerate(streams, start=1):
            test = requests.get(url, headers=HEADERS, timeout=10)
            preview.append(
                {
                    "flux": idx,
                    "url_prefix": url[:65] + "...",
                    "http_status": test.status_code,
                    "m3u8_preview": test.text[:250],
                }
            )
        return jsonify({"status": "ok", "count": len(streams), "streams": preview})
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/EVANGILETV.m3u")
@app.route("/playlist.m3u")
def playlist():
    base_url = request.host_url.rstrip("/")
    lines = ["#EXTM3U"]
    try:
        streams = get_evangiletv_streams()
        for idx in range(1, len(streams) + 1):
            suffix = "" if idx == 1 else f" (Flux {idx})"
            route = "/live.m3u8" if idx == 1 else f"/live{idx}.m3u8"
            lines.append(
                f'#EXTINF:-1 tvg-id="EVANGILETV" tvg-name="{CHANNEL_TITLE}",{CHANNEL_TITLE}{suffix}'
            )
            lines.append(f"{base_url}{route}")
    except Exception:
        lines.append(
            f'#EXTINF:-1 tvg-id="EVANGILETV" tvg-name="{CHANNEL_TITLE}",{CHANNEL_TITLE}'
        )
        lines.append(f"{base_url}/live.m3u8")

    return Response("\n".join(lines) + "\n", mimetype="audio/x-mpegurl")


@app.route("/live.m3u8")
def live_m3u8():
    try:
        streams = get_evangiletv_streams()
        return proxy_m3u8(streams[0])
    except Exception as e:
        return Response(f"Erreur flux 1 ({CHANNEL_TITLE}): {e}", status=502)


@app.route("/live2.m3u8")
def live2_m3u8():
    try:
        streams = get_evangiletv_streams()
        if len(streams) < 2:
            return Response("Deuxième flux non disponible.", status=404)
        return proxy_m3u8(streams[1])
    except Exception as e:
        return Response(f"Erreur flux 2 ({CHANNEL_TITLE}): {e}", status=502)


@app.route("/proxy")
def proxy():
    target_url = unquote(request.args.get("url", ""))
    if not target_url.startswith("http"):
        return Response("URL invalide", status=400)

    if ".m3u8" in target_url:
        return proxy_m3u8(target_url)

    r = requests.get(target_url, headers=HEADERS, stream=True, timeout=15)
    return Response(
        r.iter_content(chunk_size=32768),
        status=r.status_code,
        content_type=r.headers.get("Content-Type", "video/MP2T"),
    )


def proxy_m3u8(m3u8_url):
    r = requests.get(m3u8_url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    base_proxy = f"{request.host_url.rstrip('/')}/proxy?url="

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

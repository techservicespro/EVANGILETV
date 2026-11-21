import re
import time
from urllib.parse import quote, unquote, urljoin
from flask import Flask, Response, jsonify, request
import requests

app = Flask(__name__)

LIVE_PAGE_URL = "https://evangile.tv/direct-24-7/"
FALLBACK_API_URL = (
    "https://evangiletv-live1-p-api.hexaglobe.net/"
    "cec61441155731421275087a35fc2d98/1795022284/"
    "evangiletv/EvangileTV-website-web-1/live1/stream_info.php"
)

STREAM_CACHE = {"streams": [], "expires_at": 0, "source": ""}


def get_headers(is_api=False):
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*" if is_api else "*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://evangile.tv",
        "Referer": "https://evangile.tv/",
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


def discover_fresh_source():
    html_headers = get_headers(is_api=False)
    html_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

    r = requests.get(LIVE_PAGE_URL, headers=html_headers, timeout=10)
    r.raise_for_status()
    page_text = r.text.replace("\\/", "/")

    api_matches = re.findall(
        r'https?://[^\s"\'<>]+hexaglobe\.net/[^\s"\'<>]+stream_info\.php[^\s"\'<>]*',
        page_text,
    )
    if api_matches:
        return ("api", api_matches[0])

    m3u8_matches = re.findall(
        r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
        page_text,
    )
    if m3u8_matches:
        return ("m3u8", list(dict.fromkeys(m3u8_matches)))

    iframes = re.findall(r'<iframe[^>]+src=["\'](https?://[^"\']+)["\']', page_text, re.I)
    for iframe_url in list(dict.fromkeys(iframes)):
        try:
            sub_r = requests.get(iframe_url, headers=html_headers, timeout=10)
            sub_text = sub_r.text.replace("\\/", "/")

            sub_api = re.findall(
                r'https?://[^\s"\'<>]+hexaglobe\.net/[^\s"\'<>]+stream_info\.php[^\s"\'<>]*',
                sub_text,
            )
            if sub_api:
                return ("api", sub_api[0])

            sub_m3u8 = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', sub_text)
            if sub_m3u8:
                return ("m3u8", list(dict.fromkeys(sub_m3u8)))
        except Exception:
            continue

    return ("api", FALLBACK_API_URL)


def fetch_streams_from_api(api_url):
    r = requests.get(api_url, headers=get_headers(is_api=True), timeout=10)
    r.raise_for_status()
    try:
        streams = extract_m3u8_urls(r.json())
    except ValueError:
        raw_text = r.text.replace("\\/", "/")
        streams = list(
            dict.fromkeys(re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', raw_text))
        )
    if not streams:
        raise RuntimeError("Aucune URL .m3u8 trouvée dans stream_info.php.")
    return streams


def get_evangiletv_streams(force_refresh=False):
    now = time.time()
    if not force_refresh and STREAM_CACHE["streams"] and now < STREAM_CACHE["expires_at"]:
        return STREAM_CACHE["streams"]

    kind, target = discover_fresh_source()
    if kind == "m3u8":
        streams = target
        source_label = f"direct depuis {LIVE_PAGE_URL}"
    else:
        streams = fetch_streams_from_api(target)
        source_label = target

    STREAM_CACHE["streams"] = streams
    STREAM_CACHE["expires_at"] = now + 600
    STREAM_CACHE["source"] = source_label
    return streams


@app.route("/")
@app.route("/ping")
def index():
    return (
        "Proxy EVANGILETV actif (854x480). "
        "Flux disponibles : /EVANGILETV.m3u8, /EVANGILETV2.m3u8, /playlist.m3u, /debug"
    )


@app.route("/debug")
def debug():
    try:
        streams = get_evangiletv_streams(force_refresh=True)
        test = requests.get(streams[0], headers=get_headers(is_api=False), timeout=10)
        return jsonify(
            {
                "status": "ok",
                "source_detectee": STREAM_CACHE["source"],
                "nombre_flux": len(streams),
                "m3u8_status": test.status_code,
                "m3u8_preview": test.text[:250],
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/playlist.m3u")
def playlist():
    base_url = request.host_url.rstrip("/")
    lines = [
        "#EXTM3U",
        '#EXTINF:-1 tvg-id="EVANGILETV" tvg-name="EVANGILETV",EVANGILETV',
        f"{base_url}/EVANGILETV.m3u8",
        '#EXTINF:-1 tvg-id="EVANGILETV2" tvg-name="EVANGILETV (Flux 2)",EVANGILETV (Flux 2)',
        f"{base_url}/EVANGILETV2.m3u8",
    ]
    return Response("\n".join(lines) + "\n", mimetype="audio/x-mpegurl")


@app.route("/EVANGILETV.m3u8")
@app.route("/live.m3u8")
def evangiletv_1():
    try:
        streams = get_evangiletv_streams()
        return proxy_m3u8(streams[0])
    except Exception:
        try:
            streams = get_evangiletv_streams(force_refresh=True)
            return proxy_m3u8(streams[0])
        except Exception as e:
            return Response(f"Erreur EVANGILETV : {e}", status=502)


@app.route("/EVANGILETV2.m3u8")
@app.route("/live2.m3u8")
def evangiletv_2():
    try:
        streams = get_evangiletv_streams()
        if len(streams) < 2:
            return Response("Deuxième flux EVANGILETV non disponible.", status=404)
        return proxy_m3u8(streams[1])
    except Exception as e:
        return Response(f"Erreur EVANGILETV2 : {e}", status=502)


@app.route("/proxy")
def proxy():
    target_url = unquote(request.args.get("url", ""))
    if not target_url.startswith("http"):
        return Response("URL invalide", status=400)

    if ".m3u8" in target_url:
        return proxy_m3u8(target_url)

    r = requests.get(
        target_url, headers=get_headers(is_api=False), stream=True, timeout=15
    )
    return Response(
        r.iter_content(chunk_size=32768),
        status=r.status_code,
        content_type=r.headers.get("Content-Type", "video/MP2T"),
    )


def proxy_m3u8(m3u8_url):
    r = requests.get(m3u8_url, headers=get_headers(is_api=False), timeout=10)
    r.raise_for_status()
    base_proxy = f"{request.host_url.rstrip('/')}/proxy?url="
    lines = r.text.splitlines()

    if "#EXT-X-STREAM-INF" in r.text:
        selected_block = []
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF") and ("854x480" in line or "x480" in line or "480p" in line):
                selected_block.append(line)
                if i + 1 < len(lines) and not lines[i + 1].startswith("#"):
                    selected_block.append(lines[i + 1])
                break

        if selected_block:
            lines = ["#EXTM3U", "#EXT-X-VERSION:3"] + selected_block

    rewritten_lines = []
    for line in lines:
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

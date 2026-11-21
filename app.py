def proxy_m3u8(m3u8_url):
    r = requests.get(m3u8_url, headers=get_headers(is_api=False), timeout=10)
    r.raise_for_status()
    base_proxy = f"{request.host_url.rstrip('/')}/proxy?url="
    lines = r.text.splitlines()

    # Si c'est un manifeste maître (#EXT-X-STREAM-INF), ne garder que la variante 854x480
    if "#EXT-X-STREAM-INF" in r.text:
        selected_block = []
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF") and ("854x480" in line or "x480" in line or "480p" in line):
                selected_block.append(line)
                if i + 1 < len(lines) and not lines[i + 1].startswith("#"):
                    selected_block.append(lines[i + 1])
                break

        # Si une piste 480p a été trouvée, reconstruire le manifeste uniquement avec cette piste
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

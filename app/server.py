import os
import json
import asyncio
import logging
from aiohttp import web, ClientSession, WSMsgType
from watchfiles import awatch, Change
from metadata import process_metadata

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('tagger')

METUBE_URL = os.environ.get('METUBE_URL', 'http://metube:8081')
DOWNLOAD_DIR = os.environ.get('DOWNLOAD_DIR', '/downloads')
LISTEN_PORT = int(os.environ.get('PORT', '3010'))
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.opus', '.ogg', '.flac', '.wav'}

# In-memory state
recent_files = []  # list of dicts: {filename, path, status, tagged_at, meta}
MAX_RECENT = 50


def is_audio_file(path):
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


async def watch_downloads(app):
    """Background task: watch download folder for new audio files."""
    log.info(f"Watching {DOWNLOAD_DIR} for new audio files")
    try:
        async for changes in awatch(DOWNLOAD_DIR, recursive=True):
            for change_type, path in changes:
                if change_type == Change.added and is_audio_file(path) and os.path.isfile(path):
                    rel = os.path.relpath(path, DOWNLOAD_DIR)
                    # Skip if already tracked
                    if any(f['path'] == path for f in recent_files):
                        continue
                    entry = {
                        'filename': os.path.basename(path),
                        'rel_path': rel,
                        'path': path,
                        'status': 'new',
                        'size': os.path.getsize(path),
                        'meta': {},
                    }
                    recent_files.insert(0, entry)
                    if len(recent_files) > MAX_RECENT:
                        recent_files.pop()
                    log.info(f"New audio file detected: {rel}")

                    # Notify connected websocket clients
                    for ws in app.get('ws_clients', []):
                        try:
                            await ws.send_json({'type': 'new_file', 'file': entry})
                        except Exception:
                            pass
    except asyncio.CancelledError:
        log.info("File watcher stopped")
    except Exception as e:
        log.error(f"File watcher error: {e}")


async def start_watcher(app):
    app['watcher_task'] = asyncio.create_task(watch_downloads(app))
    app['ws_clients'] = []


async def stop_watcher(app):
    app['watcher_task'].cancel()
    try:
        await app['watcher_task']
    except asyncio.CancelledError:
        pass


# --- API routes ---

async def api_files(request):
    """Return list of tracked files."""
    return web.json_response(recent_files)


async def api_tag(request):
    """Apply metadata tags to a file."""
    data = await request.json()
    path = data.get('path')
    if not path:
        return web.json_response({'status': 'error', 'msg': 'Missing path'}, status=400)

    # Security check
    real_path = os.path.realpath(path)
    if not real_path.startswith(os.path.realpath(DOWNLOAD_DIR)):
        return web.json_response({'status': 'error', 'msg': 'Invalid path'}, status=400)

    if not os.path.isfile(path):
        return web.json_response({'status': 'error', 'msg': 'File not found'}, status=404)

    # Find entry
    entry = next((f for f in recent_files if f['path'] == path), None)
    if entry:
        entry['status'] = 'processing'
        # Notify clients
        for ws in request.app.get('ws_clients', []):
            try:
                await ws.send_json({'type': 'status', 'path': path, 'status': 'processing'})
            except Exception:
                pass

    try:
        custom_filename = data.get('custom_filename') or None
        artist = data.get('artist') or None
        album = data.get('album') or None
        use_default_cover = data.get('use_default_cover', True)
        custom_cover_data = data.get('custom_cover_data') or None

        new_path = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: process_metadata(
                path,
                custom_filename=custom_filename,
                artist=artist,
                album=album,
                use_default_cover=use_default_cover,
                custom_cover_data=custom_cover_data,
            )
        )

        if entry:
            entry['status'] = 'tagged'
            entry['path'] = new_path
            entry['filename'] = os.path.basename(new_path)
            entry['rel_path'] = os.path.relpath(new_path, DOWNLOAD_DIR)
            entry['meta'] = {
                'custom_filename': custom_filename,
                'artist': artist,
                'album': album,
                'use_default_cover': use_default_cover,
            }

        # Notify clients
        for ws in request.app.get('ws_clients', []):
            try:
                await ws.send_json({
                    'type': 'status',
                    'path': path,
                    'new_path': new_path,
                    'status': 'tagged',
                    'entry': entry,
                })
            except Exception:
                pass

        log.info(f"Tagged: {path} -> {new_path}")
        return web.json_response({'status': 'ok', 'new_path': new_path})

    except Exception as e:
        log.error(f"Tagging failed for {path}: {e}")
        if entry:
            entry['status'] = 'error'
        return web.json_response({'status': 'error', 'msg': str(e)}, status=500)


async def api_skip(request):
    """Mark a file as skipped."""
    data = await request.json()
    path = data.get('path')
    entry = next((f for f in recent_files if f['path'] == path), None)
    if entry:
        entry['status'] = 'skipped'
    return web.json_response({'status': 'ok'})


async def websocket_handler(request):
    """WebSocket for real-time updates."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app['ws_clients'].append(ws)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.CLOSE:
                break
    finally:
        request.app['ws_clients'].remove(ws)
    return ws


# --- MeTube proxy ---

async def proxy_metube(request):
    """Proxy all requests to MeTube."""
    path = request.match_info.get('path', '')
    url = f"{METUBE_URL}/{path}"
    if request.query_string:
        url += f"?{request.query_string}"

    async with ClientSession() as session:
        try:
            method = request.method.lower()
            headers = {}
            # Forward relevant headers
            for h in ('content-type', 'accept', 'accept-encoding'):
                if h in request.headers:
                    headers[h] = request.headers[h]

            body = await request.read() if request.can_read_body else None

            async with session.request(method, url, headers=headers, data=body) as resp:
                response_headers = {}
                for h in ('content-type', 'cache-control', 'etag'):
                    if h in resp.headers:
                        response_headers[h] = resp.headers[h]

                data = await resp.read()
                return web.Response(body=data, status=resp.status, headers=response_headers)
        except Exception as e:
            log.error(f"Proxy error: {e}")
            return web.Response(text=f"Proxy error: {e}", status=502)


async def proxy_metube_ws(request):
    """Proxy WebSocket connections to MeTube's socket.io."""
    path = request.match_info.get('path', '')
    url = f"{METUBE_URL}/{path}"
    if request.query_string:
        url += f"?{request.query_string}"

    ws_client = web.WebSocketResponse()
    await ws_client.prepare(request)

    ws_url = url.replace('http://', 'ws://').replace('https://', 'wss://')

    async with ClientSession() as session:
        try:
            async with session.ws_connect(ws_url) as ws_server:
                async def forward_to_client():
                    async for msg in ws_server:
                        if msg.type == WSMsgType.TEXT:
                            await ws_client.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await ws_client.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break

                async def forward_to_server():
                    async for msg in ws_client:
                        if msg.type == WSMsgType.TEXT:
                            await ws_server.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await ws_server.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break

                await asyncio.gather(forward_to_client(), forward_to_server())
        except Exception as e:
            log.debug(f"WS proxy ended: {e}")

    return ws_client


# --- Main page ---

async def index(request):
    """Serve the unified wrapper page."""
    html_path = os.path.join(os.path.dirname(__file__), 'index.html')
    return web.FileResponse(html_path)


# --- App setup ---

app = web.Application()

# Tagger routes
app.router.add_get('/', index)
app.router.add_get('/tagger/ws', websocket_handler)
app.router.add_get('/tagger/files', api_files)
app.router.add_post('/tagger/tag', api_tag)
app.router.add_post('/tagger/skip', api_skip)

# MeTube socket.io proxy (must come before general proxy)
app.router.add_get('/socket.io/{path:.*}', proxy_metube_ws)
app.router.add_post('/socket.io/{path:.*}', proxy_metube)

# MeTube proxy (catch-all, must be last)
app.router.add_route('*', '/metube/{path:.*}', proxy_metube)
app.router.add_route('*', '/metube', proxy_metube)

app.on_startup.append(start_watcher)
app.on_cleanup.append(stop_watcher)

if __name__ == '__main__':
    log.info(f"Starting tagger on port {LISTEN_PORT}, proxying MeTube at {METUBE_URL}")
    web.run_app(app, host='0.0.0.0', port=LISTEN_PORT)

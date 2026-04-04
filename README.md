# MeTube + Audio Tagger

A wrapper around [MeTube](https://github.com/alexta69/metube) that adds audio metadata tagging (filename, artist, album, cover art) as a post-processing step.

MeTube stays **completely stock and unmodified**. The tagger runs as a separate container that watches the download folder and lets you tag files after they're downloaded.

## How it works

1. Visit `http://localhost:3010` — one page with MeTube on top, tagger below
2. Download audio from MeTube as normal
3. New audio files appear in the tagger panel automatically
4. Fill in filename, artist, album, toggle default cover
5. Click "Apply tags" — metadata is written and file is renamed
6. Done

## Setup

```bash
docker compose up -d
```

Then open `http://localhost:3010`.

## Configuration

Edit `docker-compose.yml` to change:

- **Download path**: Change `/mnt/sec/media/music` to your download directory (must match in both services)
- **Port**: Change `3010:3010` to use a different port
- **MeTube config**: Change `/mnt/sec/apps/metube/config` to your MeTube config path

## Updating MeTube

Since MeTube is stock, just pull the latest image:

```bash
docker compose pull metube
docker compose up -d
```

No merge conflicts. No patches. No forks to maintain.

## Supported formats

The tagger supports: MP3, M4A, OGG, Opus, FLAC, WAV (WAV has no metadata support)

## Files

```
├── app/
│   ├── server.py          # Proxy + tagger API + file watcher
│   ├── index.html          # Unified wrapper UI
│   ├── metadata.py         # Audio metadata processor
│   └── default_cover.png   # Default cover art
├── Dockerfile
├── docker-compose.yml
└── README.md
```

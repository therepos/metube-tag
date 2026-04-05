## Usage

Deploy via docker compose.

## Structure

```
├── app/
│   ├── server.py               # Proxy + tagger API + file watcher
│   ├── index.html              # Unified wrapper UI
│   ├── metadata.py             # Audio metadata processor
│   └── default_cover.png       # Default cover art
├── static/
│   └── img/
│       └── default_cover.png   # Default cover art
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Resources

- [alexta69/metube](https://github.com/alexta69/metube)



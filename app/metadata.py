import os
import logging
import base64
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, APIC, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.flac import FLAC, Picture

log = logging.getLogger('metadata')

DEFAULT_COVER_PATH = os.path.join(os.path.dirname(__file__), 'default_cover.png')


def _read_cover_image(cover_source: str | None, use_default_cover: bool) -> bytes | None:
    """Read cover image bytes from base64 string or default file."""
    if cover_source:
        try:
            # cover_source is base64-encoded image data
            return base64.b64decode(cover_source)
        except Exception as e:
            log.warning(f"Failed to decode custom cover image: {e}")

    if use_default_cover and os.path.isfile(DEFAULT_COVER_PATH):
        try:
            with open(DEFAULT_COVER_PATH, 'rb') as f:
                return f.read()
        except Exception as e:
            log.warning(f"Failed to read default cover image: {e}")

    return None


def _detect_mime_type(data: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if data[:2] == b'\xff\xd8':
        return 'image/jpeg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return 'image/png'  # fallback


def _strip_and_write_id3(filepath: str, title: str | None, artist: str | None, album: str | None, cover_data: bytes | None):
    """Handle MP3 files using ID3 tags."""
    try:
        tags = ID3(filepath)
        tags.delete(filepath)
    except ID3NoHeaderError:
        pass

    tags = ID3()

    if title:
        tags.add(TIT2(encoding=3, text=[title]))
    if artist:
        tags.add(TPE1(encoding=3, text=[artist]))
        tags.add(TPE2(encoding=3, text=[artist]))
    if album:
        tags.add(TALB(encoding=3, text=[album]))
    if cover_data:
        mime = _detect_mime_type(cover_data)
        tags.add(APIC(
            encoding=3,
            mime=mime,
            type=3,  # Cover (front)
            desc='Cover',
            data=cover_data
        ))

    tags.save(filepath)
    log.info(f"ID3 metadata written to {filepath}")


def _strip_and_write_mp4(filepath: str, title: str | None, artist: str | None, album: str | None, cover_data: bytes | None):
    """Handle M4A/MP4 files."""
    audio = MP4(filepath)

    # Strip all existing tags
    audio.clear()
    audio.save()

    # Re-open and write new tags
    audio = MP4(filepath)

    if title:
        audio['\xa9nam'] = [title]
    if artist:
        audio['\xa9ART'] = [artist]
        audio['aART'] = [artist]
    if album:
        audio['\xa9alb'] = [album]
    if cover_data:
        mime = _detect_mime_type(cover_data)
        img_format = MP4Cover.FORMAT_PNG if 'png' in mime else MP4Cover.FORMAT_JPEG
        audio['covr'] = [MP4Cover(cover_data, imageformat=img_format)]

    audio.save()
    log.info(f"MP4 metadata written to {filepath}")


def _strip_and_write_ogg(filepath: str, title: str | None, artist: str | None, album: str | None, cover_data: bytes | None):
    """Handle OGG Opus/Vorbis files."""
    audio = MutagenFile(filepath)
    if audio is None:
        log.warning(f"Could not open OGG file: {filepath}")
        return

    # Strip all existing tags
    audio.delete()
    audio.save()

    # Re-open and write
    audio = MutagenFile(filepath)

    if title:
        audio['title'] = [title]
    if artist:
        audio['artist'] = [artist]
        audio['albumartist'] = [artist]
    if album:
        audio['album'] = [album]
    if cover_data:
        mime = _detect_mime_type(cover_data)
        picture = Picture()
        picture.type = 3  # Cover (front)
        picture.mime = mime
        picture.desc = 'Cover'
        picture.data = cover_data
        # OGG stores pictures as base64-encoded FLAC picture blocks
        encoded = base64.b64encode(picture.write()).decode('ascii')
        audio['metadata_block_picture'] = [encoded]

    audio.save()
    log.info(f"OGG metadata written to {filepath}")


def _strip_and_write_flac(filepath: str, title: str | None, artist: str | None, album: str | None, cover_data: bytes | None):
    """Handle FLAC files."""
    audio = FLAC(filepath)

    # Strip all existing tags and pictures
    audio.delete()
    audio.clear_pictures()
    audio.save()

    # Re-open and write
    audio = FLAC(filepath)

    if title:
        audio['title'] = [title]
    if artist:
        audio['artist'] = [artist]
        audio['albumartist'] = [artist]
    if album:
        audio['album'] = [album]
    if cover_data:
        mime = _detect_mime_type(cover_data)
        picture = Picture()
        picture.type = 3  # Cover (front)
        picture.mime = mime
        picture.desc = 'Cover'
        picture.data = cover_data
        audio.add_picture(picture)

    audio.save()
    log.info(f"FLAC metadata written to {filepath}")


def process_metadata(
    filepath: str,
    custom_filename: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    use_default_cover: bool = True,
    custom_cover_data: str | None = None,
) -> str:
    """
    Process audio file metadata: strip existing tags, write new ones, embed cover art, rename file.

    Args:
        filepath: Path to the downloaded audio file
        custom_filename: Custom filename (without extension) - also used as the title tag
        artist: Artist tag value
        album: Album tag value
        use_default_cover: Whether to embed the default cover image
        custom_cover_data: Base64-encoded custom cover image data (overrides default)

    Returns:
        The (possibly renamed) filepath
    """
    # Check if there's anything to do
    has_metadata = any([custom_filename, artist, album])
    has_cover = use_default_cover or custom_cover_data

    if not has_metadata and not has_cover:
        log.info(f"No metadata changes requested for {filepath}")
        return filepath

    if not os.path.isfile(filepath):
        log.warning(f"File not found for metadata processing: {filepath}")
        return filepath

    ext = os.path.splitext(filepath)[1].lower()
    title = custom_filename  # filename field = title tag

    # Read cover image
    cover_data = _read_cover_image(custom_cover_data, use_default_cover)

    try:
        if ext == '.mp3':
            _strip_and_write_id3(filepath, title, artist, album, cover_data)
        elif ext in ('.m4a', '.mp4'):
            _strip_and_write_mp4(filepath, title, artist, album, cover_data)
        elif ext in ('.opus', '.ogg'):
            _strip_and_write_ogg(filepath, title, artist, album, cover_data)
        elif ext == '.flac':
            _strip_and_write_flac(filepath, title, artist, album, cover_data)
        elif ext == '.wav':
            log.info(f"WAV format does not support metadata tags, skipping: {filepath}")
        else:
            log.warning(f"Unsupported audio format for metadata: {ext}")
    except Exception as e:
        log.error(f"Failed to process metadata for {filepath}: {e}")

    # Rename file if custom filename was provided
    if custom_filename:
        directory = os.path.dirname(filepath)
        new_filepath = os.path.join(directory, custom_filename + ext)

        # Avoid overwriting if same name
        if new_filepath != filepath:
            # Handle name conflicts
            counter = 1
            base_new_filepath = new_filepath
            while os.path.exists(new_filepath) and new_filepath != filepath:
                name_no_ext = custom_filename + f' ({counter})'
                new_filepath = os.path.join(directory, name_no_ext + ext)
                counter += 1

            try:
                os.rename(filepath, new_filepath)
                log.info(f"Renamed {filepath} -> {new_filepath}")
                filepath = new_filepath
            except Exception as e:
                log.error(f"Failed to rename file: {e}")

    return filepath

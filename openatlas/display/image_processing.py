from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from flask import flash, g
from flask_babel import gettext as _
from wand.image import Image

from openatlas import app
from openatlas.display.util2 import get_file_path
from openatlas.models.entity import Entity

# Todo: Refactor resize image

def resize_image(filename: str) -> None:
    file_format = '.' + filename.split('.', 1)[1].lower()
    if file_format in g.display_file_ext:
        for size in app.config['IMAGE_SIZE'].values():
            _safe_resize_image(
                filename.rsplit('.', 1)[0].lower(),
                file_format, size)


def _safe_resize_image(name: str, file_format: str, size: str) -> bool:
    try:
        if _check_if_folder_exist(size, app.config['RESIZED_IMAGES']):
            return _image_resizing(name, file_format, size)
        return False  # pragma: no cover
    except OSError as e:  # pragma: no cover
        g.logger.log(
            'info',
            'image processing',
            'failed to save resized image',
            e)
        return False


def _image_resizing(name: str, format_: str, size: str) -> bool:
    filename = Path(app.config['UPLOAD_PATH']) / f'{name}{format_}[0]'
    with Image(filename=filename) as src:
        if format_ in app.config['PROCESSABLE_EXT']:
            format_ = app.config['PROCESSED_EXT']  # pragma: no cover
        with src.convert(format_.replace('.', '')) as img:
            img.transform(resize=f"{size}x{size}>")
            img.compression_quality = 75
            img.save(
                filename=Path(
                    app.config['RESIZED_IMAGES']) / size / f'{name}{format_}')
            return True


def check_processed_image(filename: str) -> bool:
    file_format = '.' + filename.split('.', 1)[1].lower()
    check = False
    try:
        if file_format in g.display_file_ext:
            check = _loop_through_processed_folders(
                filename.rsplit('.', 1)[0].lower(),
                file_format)
    except OSError as e:  # pragma: no cover
        g.logger.log(
            'info',
            'image processing',
            'failed to validate file as image',
            e)
    return check


def _loop_through_processed_folders(name: str, file_format: str) -> bool:
    ext = file_format
    if file_format in app.config['PROCESSABLE_EXT']:
        ext = app.config['PROCESSED_EXT']  # pragma: no cover
    for size in app.config['IMAGE_SIZE'].values():
        path = Path(app.config['RESIZED_IMAGES']) / size / f'{name}{ext}'
        if not path.is_file() \
                and not _safe_resize_image(name, file_format, size):
            return False  # pragma: no cover
    return True


def _check_if_folder_exist(folder: str, path: str) -> bool:
    folder_to_check = Path(path) / folder
    return True if folder_to_check.is_dir() else _create_folder(folder_to_check)


def _create_folder(folder: Path) -> bool:  # pragma: no cover
    try:
        folder.mkdir()
        return True
    except OSError as e:
        g.logger.log('info', 'image processing', 'failed to create folder', e)
        return False


def delete_orphaned_resized() -> None:
    for size in app.config['IMAGE_SIZE'].values():
        path = Path(app.config['RESIZED_IMAGES']) / size
        for file in path.glob('**/*'):
            file_name = file.name.rsplit('.', 1)[0].lower()
            if not file_name.isdigit() or int(file_name) not in g.files:
                file.unlink()


def create_resized_images() -> None:
    for e in Entity.get_by_class('file'):
        if e.id in g.files and e.get_file_ext() in g.display_file_ext:
            resize_image(f"{e.id}{e.get_file_ext()}")


def check_iiif_activation() -> bool:
    return bool(
        g.settings['iiif'] and os.access(
            Path(g.settings['iiif_path']),
            os.W_OK))


def check_iiif_file_exist(id_: int) -> bool:
    if g.settings['iiif_conversion']:
        return get_iiif_file_path(id_).is_file()
    return bool(get_file_path(id_))  # pragma: no cover


def get_iiif_file_path(id_: int) -> Path:
    ext = '.tiff' if g.settings['iiif_conversion'] else g.files[id_].suffix
    return Path(g.settings['iiif_path']) / f'{id_}{ext}'


def delete_iiif_image(id_: int) -> None:
    get_iiif_file_path(id_).unlink(missing_ok=True)


def convert_image_to_iiif(id_: int, path: Optional[Path] = None) -> bool:
    vips_path = get_binary_path('vips', required=True)
    if not vips_path:  # pragma: no cover
        return False
    source = str(path or get_file_path(id_))
    target = str(get_iiif_file_path(id_))
    env = os.environ.copy()
    env["VIPS_WARNING"] = "0"
    command = [
        vips_path,
        'tiffsave',
        source,
        target,
        '--tile',
        '--pyramid',
        '--compression', g.settings['iiif_conversion'],
        '--tile-width', '128',
        '--tile-height', '128']
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            text=True)
    except subprocess.CalledProcessError as e:  # pragma: no cover
        error_msg = e.stderr.strip() if e.stderr else "Unknown vips error"
        g.logger.log(
            'error',
            'iiif_conversion',
            f'Vips failed for ID {id_} ({e.returncode}): {error_msg}')
        return False
    except Exception as e:  # pragma: no cover
        g.logger.log(
            'error',
            'iiif_conversion',
            f'Unexpected error during Vips conversion for ID {id_}: {str(e)}')
        return False
    return True


def get_binary_path(name: str, required: bool = False) -> str | None:
    binary_path = shutil.which(name)
    if not binary_path:  # pragma: no cover
        msg = f'{_('system tool not found')}: {name}'
        flash(msg, 'error' if required else 'warning')
        return None
    return binary_path

"""WikiOracle Dropbox storage helpers.

Thin wrapper around the Dropbox SDK for uploading/downloading
encrypted ZIP archives to/from a Dropbox App Folder.
"""

from __future__ import annotations

import dropbox
from dropbox.files import WriteMode


def _make_client(access_token: str, refresh_token: str,
                 app_key: str, app_secret: str) -> dropbox.Dropbox:
    """Create a Dropbox client with auto-refresh capability."""
    return dropbox.Dropbox(
        oauth2_access_token=access_token,
        oauth2_refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret,
    )


def upload_file(access_token: str, refresh_token: str,
                app_key: str, app_secret: str,
                path: str, data: bytes) -> None:
    """Upload *data* to *path* in the Dropbox App Folder (overwrite)."""
    dbx = _make_client(access_token, refresh_token, app_key, app_secret)
    dbx.files_upload(data, path, mode=WriteMode.overwrite)


def download_file(access_token: str, refresh_token: str,
                  app_key: str, app_secret: str,
                  path: str) -> bytes:
    """Download and return the bytes at *path* from Dropbox."""
    dbx = _make_client(access_token, refresh_token, app_key, app_secret)
    _meta, response = dbx.files_download(path)
    return response.content


def create_shared_link(access_token: str, refresh_token: str,
                       app_key: str, app_secret: str,
                       path: str) -> str:
    """Return a shared link URL for *path*, creating one if needed."""
    dbx = _make_client(access_token, refresh_token, app_key, app_secret)
    try:
        meta = dbx.sharing_create_shared_link_with_settings(path)
        return meta.url
    except dropbox.exceptions.ApiError as e:
        if e.error.is_shared_link_already_exists():
            links = dbx.sharing_list_shared_links(path=path, direct_only=True)
            if links.links:
                return links.links[0].url
        raise


def file_exists(access_token: str, refresh_token: str,
                app_key: str, app_secret: str,
                path: str) -> bool:
    """Return True if *path* exists in the Dropbox App Folder."""
    dbx = _make_client(access_token, refresh_token, app_key, app_secret)
    try:
        dbx.files_get_metadata(path)
        return True
    except dropbox.exceptions.ApiError:
        return False

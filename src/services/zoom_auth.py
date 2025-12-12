# src/services/zoom_auth.py
"""
Zoom OAuth Authentication — Supports Both General and Server-to-Server Apps

- General OAuth: Uses stored access_token and refresh_token
- Server-to-Server: Uses account_credentials grant
"""

import logging
import time
import base64
import requests
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


class ZoomAuthError(Exception):
    """Raised when Zoom authentication fails."""

    pass


class ZoomAuth:
    """Manages Zoom OAuth tokens with automatic refresh."""

    _token: Optional[str] = None
    _token_expires_at: float = 0
    _initialized: bool = False  # Track if we've loaded from .env

    @classmethod
    def get_access_token(cls, force_refresh: bool = False) -> str:
        """Get a valid access token, refreshing if needed."""

        # First time: load token from .env
        if not cls._initialized and settings.ZOOM_ACCESS_TOKEN:
            logger.info("Loading access token from .env")
            cls._token = settings.ZOOM_ACCESS_TOKEN
            cls._token_expires_at = time.time() + 300  # Assume valid for 5 min
            cls._initialized = True

        # Force refresh if requested (e.g., after 401 error)
        if force_refresh:
            logger.info("Force refreshing token...")
            cls._refresh_token()
            return cls._token

        # Check if we have a valid cached token
        if cls._token and time.time() < cls._token_expires_at - 60:
            return cls._token

        # Need to refresh
        cls._refresh_token()
        return cls._token

    @classmethod
    def _refresh_token(cls) -> None:
        """Refresh the access token using the appropriate method."""
        client_id = settings.ZOOM_CLIENT_ID
        client_secret = settings.ZOOM_CLIENT_SECRET

        if not client_id or not client_secret:
            raise ZoomAuthError("Missing ZOOM_CLIENT_ID or ZOOM_CLIENT_SECRET")

        # Create Basic auth header
        credentials = f"{client_id}:{client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()

        # Check if we're using General OAuth (has refresh token)
        refresh_token = settings.ZOOM_REFRESH_TOKEN

        if refresh_token:
            cls._refresh_with_refresh_token(auth_header, refresh_token)
        else:
            # Fall back to Server-to-Server OAuth
            cls._refresh_server_to_server(auth_header)

    @classmethod
    def _refresh_with_refresh_token(cls, auth_header: str, refresh_token: str) -> None:
        """Refresh using General OAuth refresh token flow."""
        logger.info("Calling Zoom OAuth token endpoint with refresh_token...")

        try:
            response = requests.post(
                "https://zoom.us/oauth/token",
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=30,
            )

            logger.info(f"Zoom token response status: {response.status_code}")

            if response.status_code != 200:
                logger.error(
                    f"Token refresh failed: {response.status_code} {response.text}"
                )
                raise ZoomAuthError(
                    f"Token refresh failed: {response.status_code} - {response.text}"
                )

            data = response.json()
            cls._token = data["access_token"]
            cls._token_expires_at = time.time() + data.get("expires_in", 3600)

            logger.info(
                f"✅ New access token obtained! Expires in {data.get('expires_in', 3600)}s"
            )

            # Log new refresh token if provided (should update .env manually)
            new_refresh = data.get("refresh_token")
            if new_refresh and new_refresh != refresh_token:
                logger.warning(
                    f"⚠️ NEW REFRESH TOKEN ISSUED! Update your .env:\n"
                    f"ZOOM_REFRESH_TOKEN={new_refresh}"
                )

        except requests.RequestException as e:
            logger.error(f"Token refresh request failed: {e}")
            raise ZoomAuthError(f"Network error during token refresh: {e}")

    @classmethod
    def _refresh_server_to_server(cls, auth_header: str) -> None:
        """Refresh using Server-to-Server OAuth."""
        account_id = settings.ZOOM_ACCOUNT_ID

        if not account_id:
            raise ZoomAuthError(
                "No refresh token for General OAuth and no ZOOM_ACCOUNT_ID for Server-to-Server. "
                "Please provide ZOOM_REFRESH_TOKEN or ZOOM_ACCOUNT_ID."
            )

        logger.info("Getting token using Server-to-Server OAuth...")

        try:
            response = requests.post(
                "https://zoom.us/oauth/token",
                params={
                    "grant_type": "account_credentials",
                    "account_id": account_id,
                },
                headers={
                    "Authorization": f"Basic {auth_header}",
                },
                timeout=30,
            )

            if response.status_code != 200:
                logger.error(f"S2S auth failed: {response.status_code} {response.text}")
                raise ZoomAuthError(f"S2S auth failed: {response.status_code}")

            data = response.json()
            cls._token = data["access_token"]
            cls._token_expires_at = time.time() + data.get("expires_in", 3600)

            logger.info("✅ Zoom access token obtained (Server-to-Server)")

        except requests.RequestException as e:
            logger.error(f"S2S auth request failed: {e}")
            raise ZoomAuthError(f"Network error during S2S auth: {e}")

    @classmethod
    def download_recording(cls, url: str) -> bytes:
        """Download a recording file using OAuth token."""
        token = cls.get_access_token()

        try:
            logger.info(f"Downloading with token: {token[:20]}...")
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=300,  # 5 minutes for large files
            )

            if response.status_code == 401:
                # Token expired, FORCE refresh and retry
                logger.warning("Got 401 - forcing token refresh...")
                token = cls.get_access_token(force_refresh=True)

                logger.info(f"Retrying download with new token: {token[:20]}...")
                response = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=300,
                )

            if response.status_code != 200:
                logger.error(
                    f"Download failed: {response.status_code} {response.text[:200]}"
                )
                raise ZoomAuthError(f"Download failed: {response.status_code}")

            logger.info(f"✅ Downloaded {len(response.content)} bytes")
            return response.content

        except requests.RequestException as e:
            logger.error(f"Download request failed: {e}")
            raise ZoomAuthError(f"Network error during download: {e}")

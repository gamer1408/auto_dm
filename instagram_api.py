import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import httpx

from config import settings

logger = logging.getLogger("c2.instagram")

GRAPH_BASE = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}"


class InstagramAPI:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=20.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def validate_account(self, ig_user_id: str, access_token: str) -> Tuple[bool, str, str]:
        """Validate IG Business Account ID & Token. Returns (ok, username, error_msg)."""
        url = f"{GRAPH_BASE}/{ig_user_id}"
        params = {"fields": "id,username,name", "access_token": access_token}
        try:
            resp = await self._client.get(url, params=params)
            data = resp.json()
            if resp.status_code == 200 and data.get("id"):
                return True, data.get("username") or data.get("name") or ig_user_id, ""
            err = data.get("error", {}).get("message", f"HTTP {resp.status_code}")
            return False, "", err
        except Exception as exc:
            logger.exception("IG validate error")
            return False, "", str(exc)

    async def get_recent_media(
        self, ig_user_id: str, access_token: str, limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Fetch latest posts/Reels for 1-click selection or URL shortcode matching."""
        url = f"{GRAPH_BASE}/{ig_user_id}/media"
        params = {
            "fields": "id,caption,media_type,media_product_type,permalink,timestamp",
            "limit": limit,
            "access_token": access_token,
        }
        try:
            resp = await self._client.get(url, params=params)
            data = resp.json()
            if resp.status_code == 200:
                return data.get("data", [])
            logger.warning("get_recent_media failed: %s", data)
            return []
        except Exception:
            logger.exception("get_recent_media exception")
            return []

    async def find_media_by_url(
        self, ig_user_id: str, access_token: str, reel_url: str
    ) -> Optional[Dict[str, Any]]:
        """Extract shortcode from Instagram URL and match against account media."""
        shortcode = extract_shortcode(reel_url)
        if not shortcode:
            return None
        media_list = await self.get_recent_media(ig_user_id, access_token, limit=50)
        for item in media_list:
            permalink = item.get("permalink", "")
            if shortcode in permalink:
                return item
        return None

    async def reply_to_comment(
        self, comment_id: str, message: str, access_token: str
    ) -> Tuple[bool, str]:
        """Publicly reply under the commenter's comment."""
        url = f"{GRAPH_BASE}/{comment_id}/replies"
        payload = {"message": message, "access_token": access_token}
        try:
            resp = await self._client.post(url, data=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("id"):
                return True, str(data["id"])
            err = data.get("error", {}).get("message", str(data))
            logger.warning("reply_to_comment error (%s): %s", comment_id, err)
            return False, err
        except Exception as exc:
            logger.exception("reply_to_comment exception")
            return False, str(exc)

    async def send_private_reply_to_comment(
        self, ig_user_id: str, comment_id: str, message: str, access_token: str
    ) -> Tuple[bool, str]:
        """Official Meta Private Reply endpoint — opens DM directly from a comment."""
        url = f"{GRAPH_BASE}/{ig_user_id}/messages"
        payload = {
            "recipient": {"comment_id": comment_id},
            "message": {"text": message},
        }
        params = {"access_token": access_token}
        try:
            resp = await self._client.post(url, params=params, json=payload)
            data = resp.json()
            if resp.status_code == 200 and (data.get("message_id") or data.get("recipient_id")):
                return True, str(data.get("recipient_id", ""))
            err = data.get("error", {}).get("message", str(data))
            logger.warning("private_reply error (%s): %s", comment_id, err)
            return False, err
        except Exception as exc:
            logger.exception("private_reply exception")
            return False, str(exc)

    async def send_dm(
        self, ig_user_id: str, recipient_id: str, message: str, access_token: str
    ) -> Tuple[bool, str]:
        """Send standard Direct Message inside 24-hour window."""
        url = f"{GRAPH_BASE}/{ig_user_id}/messages"
        payload = {
            "recipient": {"id": str(recipient_id)},
            "message": {"text": message},
        }
        params = {"access_token": access_token}
        try:
            resp = await self._client.post(url, params=params, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("message_id"):
                return True, str(data["message_id"])
            err = data.get("error", {}).get("message", str(data))
            logger.warning("send_dm error (%s): %s", recipient_id, err)
            return False, err
        except Exception as exc:
            logger.exception("send_dm exception")
            return False, str(exc)


def extract_shortcode(url: str) -> Optional[str]:
    """Extract Instagram shortcode from /reel/<CODE>/ or /p/<CODE>/ URLs."""
    match = re.search(r"instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)", url.strip())
    return match.group(1) if match else None


ig_api = InstagramAPI()

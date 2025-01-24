from datetime import datetime, timezone
from functools import lru_cache
import logging
import re
import requests
from .schemas import PuzzleSchema, PuzzleHuntPiecesSchema

logger = logging.getLogger(__name__)

ERROR_INVALID_LINK = "Invalid link format: shareId not found"
ERROR_API_RESPONSE = "Error in API response"
ERROR_REQUEST_FAILED = "Request to API failed"


@lru_cache(maxsize=128)
def get_puzzle_data(unique_code: str) -> str | None:
    """Get puzzle token by unique_code with caching.

    Args:
        unique_code: Unique code of the puzzle

    Returns:
        token if found, None otherwise

    """
    try:
        puzzle = next(
            (p for p in PuzzleSchema.objects.all() if p.unique_code == unique_code),
            None,
        )
        if puzzle:
            return puzzle.token
        return None
    except Exception:
        logger.exception("Error fetching puzzle data")
        return None


def check_puzzle_link(link: str) -> tuple[bool, str | None, int | None]:
    """Check puzzle link validity and return status with additional info.

    Args:
        link: Puzzle share link to check

    Returns:
        Tuple containing:
        - boolean indicating if link is valid
        - token if found, None otherwise
        - piece number if found, None otherwise

    """
    try:
        share_id_match = re.match(r".*shareId=([^&]+).*", link)
        if not share_id_match:
            logger.error(ERROR_INVALID_LINK)
            return False, None, None

        share_id = share_id_match.group(1)

        with requests.Session() as session:
            response = session.get(
                "https://api2.bybit.com/spot/api/puzzle/v1/shareInfo"
                f"?shareId={share_id}",
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

        result = data.get("result", {})

        if not result or result.get("status") != 1:
            logger.warning(
                "Link is invalid (status: %d)", 
                result.get("status")
            )
            return False, None, None

        if datetime.fromisoformat(result["endTime"]) < datetime.now(
            tz=timezone.utc
        ):
            logger.warning("Puzzle has expired")
            return False, None, None

        pieces_icon = result.get("piecesIcon")
        if not pieces_icon:
            logger.warning("No pieces icon in response")
            return False, None, None

        pieces_dict = {
            piece.icon_url: piece
            for piece in PuzzleHuntPiecesSchema.pieces
        }

        matching_piece = pieces_dict.get(pieces_icon)
        if not matching_piece:
            logger.warning("No matching puzzle piece found in database")
            return False, None, None

        token = get_puzzle_data(matching_piece.unique_code)
        if not token:
            logger.warning("No matching puzzle found in database")
            return False, None, None

        if all([token, matching_piece.piece_num]):
            return True, token, matching_piece.piece_num
        return False, None, None

    except requests.exceptions.RequestException:
        logger.exception(ERROR_REQUEST_FAILED)
        return False, None, None
    except (KeyError, ValueError):
        logger.exception(ERROR_API_RESPONSE)
        return False, None, None
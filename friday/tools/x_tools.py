"""X (Twitter) tools — post, search, mentions, likes, user lookup.

Uses tweepy with X API v2. Pay-as-you-go credits.
Posting is near-free. Searching/reading costs credits.

Env vars (.env):
  X_API_KEY, X_API_SECRET, X_BEARER_TOKEN,
  X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
"""

import asyncio
import os
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity
from friday.core.config import *  # Ensures .env is loaded


def _get_client():
    """Get authenticated tweepy client."""
    import tweepy
    return tweepy.Client(
        bearer_token=os.environ.get("X_BEARER_TOKEN", ""),
        consumer_key=os.environ.get("X_CONSUMER_KEY", os.environ.get("X_API_KEY", "")),
        consumer_secret=os.environ.get("X_CONSUMER_SECRET", os.environ.get("X_API_SECRET", "")),
        access_token=os.environ.get("X_ACCESS_TOKEN", ""),
        access_token_secret=os.environ.get("X_ACCESS_TOKEN_SECRET", ""),
    )


def _check_config() -> Optional[ToolError]:
    """Check X API keys are configured."""
    # Support both naming conventions
    has_consumer = (os.environ.get("X_CONSUMER_KEY") or os.environ.get("X_API_KEY"))
    has_secret = (os.environ.get("X_CONSUMER_SECRET") or os.environ.get("X_API_SECRET"))
    required_present = [
        ("Consumer Key", has_consumer),
        ("Consumer Secret", has_secret),
        ("Bearer Token", os.environ.get("X_BEARER_TOKEN")),
        ("Access Token", os.environ.get("X_ACCESS_TOKEN")),
        ("Access Token Secret", os.environ.get("X_ACCESS_TOKEN_SECRET")),
    ]
    missing = [name for name, val in required_present if not val]
    if missing:
        return ToolError(
            code=ErrorCode.CONFIG_MISSING,
            message=f"Missing X API keys: {', '.join(missing)}. Add them to .env",
            severity=Severity.HIGH, recoverable=False)
    return None


# ═════════════════════════════════════════════════════════════════════════════
# POST / DELETE
# ═════════════════════════════════════════════════════════════════════════════


async def post_tweet(
    text: str,
    reply_to_id: Optional[str] = None,
    quote_tweet_id: Optional[str] = None,
) -> ToolResult:
    """Post a tweet. 280 chars max. Can reply or quote-tweet.

    Args:
        text: Tweet text (max 280 chars).
        reply_to_id: Tweet ID to reply to (optional).
        quote_tweet_id: Tweet ID to quote (optional).
    """
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    if len(text) > 280:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.DATA_VALIDATION,
            message=f"Tweet too long ({len(text)} chars). Max 280.",
            severity=Severity.LOW, recoverable=True))

    def _post():
        client = _get_client()
        kwargs = {"text": text}
        if reply_to_id:
            kwargs["in_reply_to_tweet_id"] = reply_to_id
        if quote_tweet_id:
            kwargs["quote_tweet_id"] = quote_tweet_id

        response = client.create_tweet(**kwargs)
        tweet_id = response.data["id"]
        return tweet_id

    try:
        tweet_id = await asyncio.to_thread(_post)
        return ToolResult(success=True, data={
            "tweet_id": tweet_id,
            "text": text,
            "url": f"https://x.com/i/web/status/{tweet_id}",
            "reply_to": reply_to_id,
            "quoted": quote_tweet_id,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Post failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def delete_tweet(tweet_id: str) -> ToolResult:
    """Delete a tweet by ID."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    try:
        await asyncio.to_thread(lambda: _get_client().delete_tweet(tweet_id))
        return ToolResult(success=True, data={"deleted": tweet_id})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Delete failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# READ — MENTIONS
# ═════════════════════════════════════════════════════════════════════════════


async def get_my_mentions(max_results: int = 10) -> ToolResult:
    """Get recent @mentions of Travis's account."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    def _mentions():
        client = _get_client()
        me = client.get_me()
        user_id = me.data.id

        mentions = client.get_users_mentions(
            id=user_id,
            max_results=min(max_results, 100),
            tweet_fields=["created_at", "author_id", "text", "public_metrics"],
            expansions=["author_id"],
            user_fields=["name", "username"],
        )

        results = []
        if mentions.data:
            users = {u.id: u for u in (mentions.includes or {}).get("users", [])}
            for tweet in mentions.data:
                author = users.get(tweet.author_id)
                metrics = tweet.public_metrics or {}
                results.append({
                    "tweet_id": tweet.id,
                    "text": tweet.text,
                    "author": f"@{author.username}" if author else "unknown",
                    "author_name": author.name if author else "unknown",
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "created_at": str(tweet.created_at),
                    "url": f"https://x.com/i/web/status/{tweet.id}",
                })

        return results

    try:
        results = await asyncio.to_thread(_mentions)
        return ToolResult(success=True, data={
            "mentions": results,
            "count": len(results),
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Mentions failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# SEARCH (costs credits)
# ═════════════════════════════════════════════════════════════════════════════


async def search_x(
    query: str,
    max_results: int = 10,
    sort_order: str = "recency",
) -> ToolResult:
    """Search recent tweets (last 7 days). Costs credits.

    Query syntax:
      "exact phrase"           → exact match
      from:username            → from specific user
      #hashtag lang:en         → hashtag + language
      -is:retweet              → exclude retweets (auto-added)
    """
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    def _search():
        client = _get_client()
        # Auto-exclude retweets unless already specified
        q = query if "-is:retweet" in query else f"{query} -is:retweet"

        tweets = client.search_recent_tweets(
            query=q,
            max_results=max(10, min(max_results, 100)),  # X API requires 10-100
            sort_order=sort_order,
            tweet_fields=["created_at", "author_id", "public_metrics", "text"],
            expansions=["author_id"],
            user_fields=["name", "username", "verified"],
        )

        results = []
        if tweets.data:
            users = {u.id: u for u in (tweets.includes or {}).get("users", [])}
            for tweet in tweets.data:
                author = users.get(tweet.author_id)
                metrics = tweet.public_metrics or {}
                results.append({
                    "tweet_id": tweet.id,
                    "text": tweet.text,
                    "author": f"@{author.username}" if author else "unknown",
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "replies": metrics.get("reply_count", 0),
                    "created_at": str(tweet.created_at),
                    "url": f"https://x.com/i/web/status/{tweet.id}",
                })

        return results

    try:
        results = await asyncio.to_thread(_search)
        return ToolResult(success=True, data={
            "tweets": results,
            "count": len(results),
            "query": query,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Search failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# ENGAGE — LIKE / RETWEET
# ═════════════════════════════════════════════════════════════════════════════


async def like_tweet(tweet_id: str) -> ToolResult:
    """Like a tweet."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    try:
        def _like():
            client = _get_client()
            me = client.get_me()
            client.like(me.data.id, tweet_id)
        await asyncio.to_thread(_like)
        return ToolResult(success=True, data={"liked": tweet_id})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Like failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def retweet(tweet_id: str) -> ToolResult:
    """Retweet a tweet."""
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    try:
        def _rt():
            client = _get_client()
            me = client.get_me()
            client.retweet(me.data.id, tweet_id)
        await asyncio.to_thread(_rt)
        return ToolResult(success=True, data={"retweeted": tweet_id})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Retweet failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# USER LOOKUP (costs credits)
# ═════════════════════════════════════════════════════════════════════════════


async def get_x_user(username: str) -> ToolResult:
    """Look up a public X profile by username.

    Args:
        username: X handle without @ (e.g. "elonmusk").
    """
    config_err = _check_config()
    if config_err:
        return ToolResult(success=False, error=config_err)

    # Strip @ if included
    username = username.lstrip("@")

    def _lookup():
        client = _get_client()
        user = client.get_user(
            username=username,
            user_fields=[
                "name", "username", "description", "public_metrics",
                "verified", "created_at", "location", "url",
            ],
        )
        if not user.data:
            return None

        u = user.data
        metrics = u.public_metrics or {}
        return {
            "name": u.name,
            "username": f"@{u.username}",
            "bio": u.description,
            "followers": metrics.get("followers_count", 0),
            "following": metrics.get("following_count", 0),
            "tweets": metrics.get("tweet_count", 0),
            "verified": getattr(u, "verified", False),
            "location": u.location,
            "url": u.url,
            "joined": str(u.created_at),
        }

    try:
        result = await asyncio.to_thread(_lookup)
        if result is None:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.DATA_VALIDATION,
                message=f"User @{username} not found.",
                severity=Severity.LOW, recoverable=True))
        return ToolResult(success=True, data=result)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"User lookup failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# TOOL SCHEMAS
# ═════════════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS = {
    "post_tweet": {
        "fn": post_tweet,
        "schema": {"type": "function", "function": {
            "name": "post_tweet",
            "description": "Post a tweet as Travis. 280 chars max. Can reply or quote-tweet.",
            "parameters": {"type": "object", "properties": {
                "text": {"type": "string", "description": "Tweet text (max 280 chars)"},
                "reply_to_id": {"type": "string", "description": "Tweet ID to reply to"},
                "quote_tweet_id": {"type": "string", "description": "Tweet ID to quote"},
            }, "required": ["text"]},
        }},
    },
    "delete_tweet": {
        "fn": delete_tweet,
        "schema": {"type": "function", "function": {
            "name": "delete_tweet",
            "description": "Delete one of Travis's tweets by ID.",
            "parameters": {"type": "object", "properties": {
                "tweet_id": {"type": "string", "description": "Tweet ID to delete"},
            }, "required": ["tweet_id"]},
        }},
    },
    "get_my_mentions": {
        "fn": get_my_mentions,
        "schema": {"type": "function", "function": {
            "name": "get_my_mentions",
            "description": "Get recent @mentions of Travis's X account.",
            "parameters": {"type": "object", "properties": {
                "max_results": {"type": "integer", "description": "Number of mentions (default 10)"},
            }, "required": []},
        }},
    },
    "search_x": {
        "fn": search_x,
        "schema": {"type": "function", "function": {
            "name": "search_x",
            "description": (
                "Search recent tweets (last 7 days). Costs credits — use thoughtfully. "
                "Query syntax: \"exact phrase\", from:username, #hashtag, -is:retweet."
            ),
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Number of results (default 10, max 100)"},
                "sort_order": {"type": "string", "enum": ["recency", "relevancy"], "description": "Sort order (default: recency)"},
            }, "required": ["query"]},
        }},
    },
    "like_tweet": {
        "fn": like_tweet,
        "schema": {"type": "function", "function": {
            "name": "like_tweet",
            "description": "Like a tweet.",
            "parameters": {"type": "object", "properties": {
                "tweet_id": {"type": "string", "description": "Tweet ID to like"},
            }, "required": ["tweet_id"]},
        }},
    },
    "retweet": {
        "fn": retweet,
        "schema": {"type": "function", "function": {
            "name": "retweet",
            "description": "Retweet a tweet.",
            "parameters": {"type": "object", "properties": {
                "tweet_id": {"type": "string", "description": "Tweet ID to retweet"},
            }, "required": ["tweet_id"]},
        }},
    },
    "get_x_user": {
        "fn": get_x_user,
        "schema": {"type": "function", "function": {
            "name": "get_x_user",
            "description": "Look up a public X profile by username. Costs credits.",
            "parameters": {"type": "object", "properties": {
                "username": {"type": "string", "description": "X handle (without @)"},
            }, "required": ["username"]},
        }},
    },
}

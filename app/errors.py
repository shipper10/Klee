"""Application errors. `user_message` is always safe to show in Telegram."""

from __future__ import annotations


class BotError(Exception):
    user_message = "Something went wrong. Please try again later."

    def __init__(self, user_message: str | None = None) -> None:
        if user_message:
            self.user_message = user_message
        super().__init__(self.user_message)


class ReauthRequired(BotError):
    user_message = (
        "HoYoLAB no longer accepts the saved session for this account. "
        "Use /link in private chat to connect it again."
    )


class NotesDisabled(BotError):
    user_message = (
        "Real-time notes are switched off for this account. Turn on "
        "“Real-Time Notes” in your HoYoLAB Battle Chronicle privacy settings, then try again. "
        "The bot never changes your account settings."
    )


class UpstreamUnavailable(BotError):
    user_message = "HoYoLAB is not answering right now. Please try again in a minute."


class RateLimited(BotError):
    user_message = "Please wait a few seconds before asking again."

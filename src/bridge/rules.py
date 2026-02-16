from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ForwardingRules:
    whitelist_users: frozenset[str] = field(default_factory=frozenset)
    blacklist_users: frozenset[str] = field(default_factory=frozenset)
    excluded_commands: tuple[str, ...] = ()
    ignore_bots: bool = True


def _normalized_user_id(user_id: str | int | None) -> str | None:
    if user_id is None:
        return None
    return str(user_id).strip()


def _is_excluded_command(content: str, excluded_commands: tuple[str, ...]) -> bool:
    stripped = content.strip()
    if not stripped:
        return False

    first_token = stripped.split(maxsplit=1)[0]
    return first_token in excluded_commands


def should_forward_discord(
    *,
    author_id: str | int | None,
    is_bot: bool,
    content: str,
    rules: ForwardingRules,
) -> tuple[bool, str]:
    return _should_forward(author_id=author_id, is_bot=is_bot, content=content, rules=rules)


def should_forward_telegram(
    *,
    author_id: str | int | None,
    is_bot: bool,
    content: str,
    rules: ForwardingRules,
) -> tuple[bool, str]:
    return _should_forward(author_id=author_id, is_bot=is_bot, content=content, rules=rules)


def _should_forward(
    *,
    author_id: str | int | None,
    is_bot: bool,
    content: str,
    rules: ForwardingRules,
) -> tuple[bool, str]:
    normalized_user_id = _normalized_user_id(author_id)

    if rules.ignore_bots and is_bot:
        return False, "ignored_bot"

    if normalized_user_id and normalized_user_id in rules.blacklist_users:
        return False, "blacklisted_user"

    if rules.whitelist_users:
        if not normalized_user_id or normalized_user_id not in rules.whitelist_users:
            return False, "not_whitelisted_user"

    if _is_excluded_command(content, rules.excluded_commands):
        return False, "excluded_command"

    return True, "ok"

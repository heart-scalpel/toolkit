"""Review task profile registry."""

from app.profiles.base import AnnotationProfile
from app.profiles.cozie_safety import PROFILE as COZIE_SAFETY_PROFILE

_PROFILES: dict[str, AnnotationProfile] = {
    COZIE_SAFETY_PROFILE.name: COZIE_SAFETY_PROFILE,
}


def profile_names() -> tuple[str, ...]:
    return tuple(_PROFILES)


def get_profile(name: str) -> AnnotationProfile:
    try:
        return _PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(profile_names())
        raise ValueError(f"unsupported profile: {name}; available profiles: {choices}") from exc


__all__ = ["AnnotationProfile", "get_profile", "profile_names"]

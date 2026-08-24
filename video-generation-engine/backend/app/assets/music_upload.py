"""Decision 6a/6b warnings for a BGM upload (analysis.md, 2026-08-24).

The upload endpoint deliberately accepts ANY track length (warn-don't-
reject): `mux_music` loop+trims whatever it gets, so nothing crashes -
the only cost of an awkward length is an audible one, and that cost is
the user's to accept once they have been TOLD about it. These are those
tellings: pure functions of two durations, no I/O, so they are trivially
unit-testable and safe to call from anywhere.
"""

_SECONDS_PER_MINUTE = 60


def _format_duration_s(seconds: float) -> str:
    """`95.0` -> `\"1:35\"` - the shape the decision text itself uses."""
    minutes, secs = divmod(max(int(round(seconds)), 0), _SECONDS_PER_MINUTE)
    return f"{minutes}:{secs:02d}"


def music_upload_warnings(track_duration_s: float, video_duration_s: float | None) -> list[str]:
    """What the Result page should tell the human about this upload's
    length, before the re-render bakes it in. Empty when nothing applies:
    unknown/absent video duration (no scenes yet), or a track within a
    second of the video's length."""
    if video_duration_s is None or video_duration_s <= 0 or track_duration_s <= 0:
        return []
    if abs(track_duration_s - video_duration_s) < 1.0:
        return []

    video = _format_duration_s(video_duration_s)
    track = _format_duration_s(track_duration_s)
    if track_duration_s < video_duration_s:
        loops = max(int(-(-video_duration_s // track_duration_s)), 2)
        return [
            f"Your {track} track is shorter than the ~{video} video — it will "
            f"loop about {loops} times and the seam may be audible. A longer "
            "track will sound smoother."
        ]
    return [
        f"Only the first {video} of your {track} track will be used — "
        "pre-trim the file if you want a different section."
    ]

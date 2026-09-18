"""RV-Q10 batching: contiguous uncached scenes share one TTS request,
split back so narration_fit still sees one alignment per scene.

Pure functions + one real-ffmpeg slice. No DB, no ElevenLabs.
"""

import asyncio
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.errors import PermanentError
from app.renderer.narration_slice import slice_wav
from app.timeline.narration_batch import (
    NARRATION_BATCH_JOINER,
    NarrationBatchMember,
    join_batch_text,
    plan_tts_batches,
    reject_truncated_alignment,
    split_batched_alignment,
    strip_tone_prefix,
)


def _member(scene_id: str, text: str, content_hash: str | None = None) -> NarrationBatchMember:
    return NarrationBatchMember(
        scene_id=scene_id,
        content_hash=content_hash or f"hash-{scene_id}",
        text=text,
    )


def _uniform_alignment(text: str, chars_per_second: float = 10.0) -> dict:
    return {
        "characters": list(text),
        "character_start_times_seconds": [i / chars_per_second for i in range(len(text))],
        "character_end_times_seconds": [(i + 1) / chars_per_second for i in range(len(text))],
    }


def test_all_misses_pack_into_one_batch():
    members = [_member("sc_01", "Hello"), _member("sc_02", "World")]
    batches = plan_tts_batches(members, cached_hashes=set(), max_characters=5000)
    assert len(batches) == 1
    assert [m.scene_id for m in batches[0]] == ["sc_01", "sc_02"]
    assert join_batch_text(batches[0]) == "Hello\nWorld"
    assert NARRATION_BATCH_JOINER == "\n"


def test_cached_hash_in_the_middle_breaks_the_batch():
    members = [
        _member("sc_01", "One"),
        _member("sc_02", "Two", "hash-cached"),
        _member("sc_03", "Three"),
    ]
    batches = plan_tts_batches(
        members, cached_hashes={"hash-cached"}, max_characters=5000
    )
    assert [[m.scene_id for m in b] for b in batches] == [["sc_01"], ["sc_03"]]


def test_duplicate_hash_is_not_sent_twice_and_does_not_break_the_run():
    """S1=A, S2=A, S3=C → one request for A then C. S2 reuses S1's slice."""
    a = _member("sc_01", "Hello", "hash-a")
    a_again = _member("sc_02", "Hello", "hash-a")
    c = _member("sc_03", "World", "hash-c")
    batches = plan_tts_batches([a, a_again, c], cached_hashes=set(), max_characters=5000)
    assert len(batches) == 1
    assert [m.scene_id for m in batches[0]] == ["sc_01", "sc_03"]
    assert join_batch_text(batches[0]) == "Hello\nWorld"


def test_character_cap_splits_before_overflow():
    members = [
        _member("sc_01", "Hello"),  # 5
        _member("sc_02", "World"),  # 5; joiner+5 would be 11
        _member("sc_03", "!!"),
    ]
    batches = plan_tts_batches(members, cached_hashes=set(), max_characters=10)
    assert [[m.text for m in b] for b in batches] == [["Hello"], ["World", "!!"]]


def test_single_scene_over_cap_is_still_its_own_batch():
    members = [_member("sc_01", "abcdefghijkl")]
    batches = plan_tts_batches(members, cached_hashes=set(), max_characters=10)
    assert len(batches) == 1
    assert batches[0][0].text == "abcdefghijkl"


def test_all_cached_yields_no_jobs():
    members = [_member("sc_01", "Hello"), _member("sc_02", "World")]
    batches = plan_tts_batches(
        members,
        cached_hashes={m.content_hash for m in members},
        max_characters=5000,
    )
    assert batches == []


def test_split_excludes_joiner_and_rebases_times():
    members = [_member("sc_01", "Hi"), _member("sc_02", "Yo")]
    joined = join_batch_text(members)
    assert joined == "Hi\nYo"
    alignment = _uniform_alignment(joined, chars_per_second=10.0)
    slices = split_batched_alignment(alignment, members)

    assert len(slices) == 2
    assert slices[0].alignment["characters"] == ["H", "i"]
    assert slices[1].alignment["characters"] == ["Y", "o"]
    # Joiner is between index 2 of the joined string; scene 2 starts at 0.3s.
    assert slices[0].audio_start_s == pytest.approx(0.0)
    assert slices[0].audio_end_s == pytest.approx(0.3)
    assert slices[1].audio_start_s == pytest.approx(0.3)
    assert slices[1].audio_end_s == pytest.approx(0.5)
    # Scene 1 last-char end absorbs the newline pause so shot duration
    # matches the sliced audio (0.30s, not the raw "i" end of 0.20s).
    assert slices[0].alignment["character_end_times_seconds"][-1] == pytest.approx(0.3)
    assert slices[0].alignment["character_start_times_seconds"][0] == pytest.approx(0.0)
    # Scene 2 is rebased so its first character is at t=0.
    assert slices[1].alignment["character_start_times_seconds"][0] == pytest.approx(0.0)
    assert slices[1].alignment["character_end_times_seconds"][-1] == pytest.approx(0.2)


def test_split_last_scene_does_not_absorb_trailing_padding_without_duration():
    members = [_member("sc_01", "Hi")]
    alignment = _uniform_alignment("Hi", chars_per_second=10.0)
    slices = split_batched_alignment(alignment, members)
    assert slices[0].audio_start_s == pytest.approx(0.0)
    assert slices[0].audio_end_s == pytest.approx(0.2)
    assert slices[0].alignment["character_end_times_seconds"][-1] == pytest.approx(0.2)


def test_split_last_scene_extends_to_provided_audio_duration():
    members = [_member("sc_01", "Hi")]
    alignment = _uniform_alignment("Hi", chars_per_second=10.0)
    slices = split_batched_alignment(alignment, members, audio_duration_s=0.25)
    assert slices[0].audio_end_s == pytest.approx(0.25)
    # Last char end stays the spoken end — MP3 padding is not shot time.
    assert slices[0].alignment["character_end_times_seconds"][-1] == pytest.approx(0.2)


def test_split_rejects_alignment_that_does_not_match_request_text():
    members = [_member("sc_01", "Hi"), _member("sc_02", "Yo")]
    alignment = _uniform_alignment("HiYo", chars_per_second=10.0)
    with pytest.raises(PermanentError, match="does not match the joined request text"):
        split_batched_alignment(alignment, members)


def test_split_rejects_empty_scene_text():
    members = [_member("sc_01", "Hi"), _member("sc_02", "")]
    alignment = _uniform_alignment("Hi\n", chars_per_second=10.0)
    with pytest.raises(PermanentError, match="empty narration_text"):
        split_batched_alignment(alignment, members)


# --- reject_truncated_alignment -------------------------------------
#
# Thresholds here are not invented: they come from measuring all 678
# narration rows across 33 projects on 2026-09-08. Legitimate terminal
# zero-duration runs exist (98 rows), are at most 3 characters long, and
# consist ONLY of '\n' and '।'. None has ever contained an alphanumeric
# character - which is why "a word got no audio" is the rule rather than
# a run-length threshold.


def _truncate_after(alignment: dict, spoken: int) -> dict:
    """Pin every character from `spoken` onward to the instant the audio
    stopped - exactly what ElevenLabs returned for the incident."""
    end = alignment["character_end_times_seconds"][spoken - 1]
    n = len(alignment["characters"])
    return {
        "characters": list(alignment["characters"]),
        "character_start_times_seconds": (
            alignment["character_start_times_seconds"][:spoken] + [end] * (n - spoken)
        ),
        "character_end_times_seconds": (
            alignment["character_end_times_seconds"][:spoken] + [end] * (n - spoken)
        ),
    }


def test_truncation_guard_accepts_a_healthy_alignment():
    reject_truncated_alignment(_uniform_alignment("Hello there."), request_label="sc_01")


def test_truncation_guard_accepts_trailing_unspoken_newline_and_full_stop():
    """The measured legitimate case: up to 3 trailing '\\n'/'।' with no
    audio. 98 of 678 real rows look like this - rejecting them would
    block renders that are completely fine."""
    for tail in ("\n", "\n\n", "।", "।\n\n"):
        text = "पहला वाक्य" + tail
        alignment = _uniform_alignment(text)
        pinned = _truncate_after(alignment, len(text) - len(tail))
        reject_truncated_alignment(pinned, request_label="sc_01")


def test_truncation_guard_rejects_audio_that_stopped_mid_text():
    text = "Plato का बाज़ार में बिकना, या उसकी आख़िरी सांस की सच्चाई?"
    pinned = _truncate_after(_uniform_alignment(text), 8)
    with pytest.raises(PermanentError, match="ended before its text did"):
        reject_truncated_alignment(pinned, request_label="sc_06")


def test_truncation_guard_rejects_a_short_clip_a_length_threshold_would_miss():
    """Four unspoken characters - under the longest LEGITIMATE run this
    system has ever stored would-be threshold, but they are word
    characters, so the audio really did stop early."""
    text = "hello world"
    pinned = _truncate_after(_uniform_alignment(text), len(text) - 4)
    with pytest.raises(PermanentError, match="ended before its text did"):
        reject_truncated_alignment(pinned, request_label="sc_01")


def test_truncation_guard_names_the_cap_to_lower():
    text = "abcdefghij"
    pinned = _truncate_after(_uniform_alignment(text), 3)
    with pytest.raises(PermanentError, match="_TTS_CHAR_LIMIT_BY_MODEL"):
        reject_truncated_alignment(pinned, request_label="batch sc_01..sc_09")


def test_truncation_guard_defers_shape_errors_to_the_better_reporters():
    """Malformed/empty shapes are reported with real context by
    `split_batched_alignment` and `SceneAlignment.from_raw`; this guard
    must not pre-empt them with a worse message."""
    reject_truncated_alignment(
        {
            "characters": [],
            "character_start_times_seconds": [],
            "character_end_times_seconds": [],
        },
        request_label="sc_01",
    )
    reject_truncated_alignment(
        {
            "characters": ["a", "b"],
            "character_start_times_seconds": [0.0],
            "character_end_times_seconds": [0.1],
        },
        request_label="sc_01",
    )
    with pytest.raises(PermanentError, match="malformed narration alignment"):
        reject_truncated_alignment({"characters": ["a"]}, request_label="sc_01")


async def test_fake_provider_alignment_splits_back_to_scene_text():
    """DRY_RUN's character-level fake still round-trips a batched request."""
    from app.providers.base import NarrationRequest
    from app.providers.fakes.narration import FakeNarrationProvider

    members = [_member("sc_01", "Hello"), _member("sc_02", "World")]
    result = await FakeNarrationProvider().synthesize(
        NarrationRequest(
            text=join_batch_text(members),
            voice_id="v",
            model="m",
            output_format="o",
            scene_id="sc_01",
        )
    )
    slices = split_batched_alignment(result.alignment, members)
    assert "".join(slices[0].alignment["characters"]) == "Hello"
    assert "".join(slices[1].alignment["characters"]) == "World"
    assert result.character_count == len("Hello\nWorld")


async def _decode_duration_s(
    path: Path, *, ffmpeg_binary: str, sample_rate: int = 48000
) -> float:
    """Decode `path` to raw mono PCM and measure duration from the byte
    count, not container metadata - the whole point of RV-Q12 is that a
    container's own reported duration is exactly what let the MP3
    re-encode defect (RV-Q11) hide: ffprobe happily reports a duration
    for a slightly-too-long MP3 frame grid without complaint."""
    process = await asyncio.create_subprocess_exec(
        ffmpeg_binary,
        "-v",
        "error",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace"))
    n_samples = len(stdout) // 2  # 16-bit signed PCM = 2 bytes/sample
    return n_samples / sample_rate


async def _make_sine_mp3(path: Path, duration_s: float) -> None:
    process = await asyncio.create_subprocess_exec(
        settings.ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration_s}",
        "-ar",
        "44100",
        "-b:a",
        "128k",
        "-c:a",
        "libmp3lame",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace"))


async def test_slice_wav_sum_of_consecutive_slices_matches_source(tmp_path: Path):
    """RV-Q12: the failure this exists to catch is ACCUMULATION across
    several joins, not a single slice's padding - so this cuts a source
    into 5 consecutive, contiguous pieces (the last one ending exactly at
    the source's own decoded duration, same as the real last-scene-of-a-
    batch case in `split_batched_alignment`) and asserts the SUM of their
    decoded PCM durations reproduces the source's own decoded duration to
    within 0.5ms.

    The specific duration and cut points below are not arbitrary: they
    are the smallest reproduction found (by scanning real narration-
    length durations) of a genuine, deterministic MP3 frame-quantisation
    artifact in this ffmpeg/libmp3lame build - re-encoding these exact
    cuts to MP3 (reverting RV-Q11's fix) measures a +0.90ms error on the
    slice ending at end-of-source alone (+0.92ms summed across all 5),
    comfortably past the tolerance here; the PCM/WAV slice this module
    actually produces measures +0.02ms summed. The review's original figures
    (+20.11/+10.18/+7.62ms) were withdrawn the same day - they came from
    decoding slices through `ffmpeg -i pipe:0`, which does not apply MP3
    gapless metadata and so counts encoder padding as audio. Re-measured
    from file paths the MP3 round-trip drifts +0.62ms over four slices,
    not +29.35ms. This test is therefore a ROBUSTNESS guard, not a
    regression test for a live defect: it pins the property that a slice
    is sample-exact by construction rather than by a decoder honouring
    metadata. Do not widen this tolerance to make a
    reverted regression pass.
    """
    src = tmp_path / "src.mp3"
    await _make_sine_mp3(src, 8.806)
    content = src.read_bytes()
    source_duration = await _decode_duration_s(src, ffmpeg_binary=settings.ffmpeg_binary)

    fracs = (0.0, 0.211, 0.487, 0.733, 1.0)
    boundaries = [f * source_duration for f in fracs]

    decoded_total = 0.0
    for i, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:], strict=True)):
        piece = await slice_wav(content, start, end, ffmpeg_binary=settings.ffmpeg_binary)
        piece_path = tmp_path / f"slice_{i}.wav"
        piece_path.write_bytes(piece)
        decoded_total += await _decode_duration_s(
            piece_path, ffmpeg_binary=settings.ffmpeg_binary
        )

    assert decoded_total == pytest.approx(source_duration, abs=0.0005)


async def test_slice_wav_rejects_non_positive_window():
    with pytest.raises(PermanentError, match="non-positive"):
        await slice_wav(b"not-even-mp3", 1.0, 1.0, ffmpeg_binary=settings.ffmpeg_binary)


# --- narration_tone_tags.md: eleven_v3 delivery tags -----------------
#
# The provider echoes an audio tag back in the alignment's character
# array but never speaks it. So the tag must be IN the joined request
# text (or the equality check rejects the response) and OUT of every
# per-scene alignment (or every `Shot.narration_span` offset shifts).


def _toned(scene_id: str, text: str, tone: str) -> NarrationBatchMember:
    return NarrationBatchMember(
        scene_id=scene_id, content_hash=f"hash-{scene_id}", text=text, tone=tone
    )


def test_tone_tag_is_sent_but_never_lands_in_narration_text():
    member = _toned("sc_01", "Hello", "excited")
    assert member.tts_text == "[excited] Hello"
    assert member.text == "Hello"
    assert join_batch_text([member]) == "[excited] Hello"


def test_untoned_member_is_byte_identical_to_before():
    member = _member("sc_01", "Hello")
    assert member.tts_text == "Hello"
    assert member.tone_prefix_len == 0
    assert join_batch_text([member]) == "Hello"


def test_batch_char_cap_counts_the_tag():
    # "[excited] " is 10 chars, so these two 5-char scenes are 30 with
    # the joiner and must split under a 25 cap.
    members = [_toned("sc_01", "Hello", "excited"), _toned("sc_02", "World", "excited")]
    batches = plan_tts_batches(members, cached_hashes=set(), max_characters=25)
    assert [[m.scene_id for m in b] for b in batches] == [["sc_01"], ["sc_02"]]


def test_split_strips_the_tag_and_leaves_surviving_times_untouched():
    members = [_toned("sc_01", "Hello", "excited"), _member("sc_02", "World")]
    sent = join_batch_text(members)
    assert sent == "[excited] Hello\nWorld"
    slices = split_batched_alignment(_uniform_alignment(sent), members)

    first = slices[0]
    # The character stream is back to the clean narration_text, so the
    # 1:1 contract every narration_span consumer assumes still holds.
    assert "".join(first.alignment["characters"]) == "Hello"
    assert first.text == "Hello"
    # The tag's marker time is ABSORBED into the first surviving
    # character rather than dropped: the scene's alignment must begin at
    # the same instant its audio file does, or narration_fit derives a
    # span shorter than the audio and the render drifts.
    assert first.alignment["character_start_times_seconds"][0] == pytest.approx(0.0)
    assert first.audio_start_s == pytest.approx(0.0)
    # Absorption moves ONLY that first start. "e" (the second surviving
    # character) is still where the provider put it: 11 chars in at
    # 10 chars/sec.
    assert first.alignment["character_start_times_seconds"][1] == pytest.approx(1.1)
    assert first.alignment["character_end_times_seconds"][0] == pytest.approx(1.1)

    second = slices[1]
    assert "".join(second.alignment["characters"]) == "World"


def test_split_rejects_a_response_that_dropped_the_tag():
    # If the provider ever stops echoing tags, the text-equality check
    # must fail loudly rather than silently mis-slicing every scene.
    members = [_toned("sc_01", "Hello", "excited"), _member("sc_02", "World")]
    with pytest.raises(PermanentError, match="does not match the joined request text"):
        split_batched_alignment(_uniform_alignment("Hello\nWorld"), members)


def test_every_scene_may_carry_its_own_tone():
    members = [_toned("sc_01", "Hello", "excited"), _toned("sc_02", "World", "curious")]
    sent = join_batch_text(members)
    assert sent == "[excited] Hello\n[curious] World"
    slices = split_batched_alignment(_uniform_alignment(sent), members)
    assert ["".join(s.alignment["characters"]) for s in slices] == ["Hello", "World"]


def test_strip_tone_prefix_absorbs_rather_than_drops():
    """The 2026-09-17 render bug, isolated.

    Dropping the tag's entries without absorbing their time left a
    scene's alignment starting AFTER its audio file did. narration_fit
    derives a scene's span as `scene_end - start[0]`, so every toned
    scene claimed less video than its audio ran, and the error
    accumulated across the reel - heard as the voice lagging further
    behind the picture.
    """
    alignment = _uniform_alignment("[excited] Hello")
    stripped = strip_tone_prefix(alignment, len("[excited] "))

    assert "".join(stripped["characters"]) == "Hello"
    # The invariant that was broken: starts where the audio starts.
    assert stripped["character_start_times_seconds"][0] == pytest.approx(0.0)
    # Total span is preserved, so no drift accumulates.
    assert stripped["character_end_times_seconds"][-1] == pytest.approx(
        alignment["character_end_times_seconds"][-1]
    )
    # Nothing else moved.
    assert stripped["character_start_times_seconds"][1:] == pytest.approx(
        alignment["character_start_times_seconds"][len("[excited] ") + 1 :]
    )


def test_strip_tone_prefix_is_a_no_op_without_a_tone():
    alignment = _uniform_alignment("Hello")
    assert strip_tone_prefix(alignment, 0) is alignment


def test_strip_tone_prefix_rejects_a_prefix_that_eats_everything():
    with pytest.raises(PermanentError, match="covers the whole alignment"):
        strip_tone_prefix(_uniform_alignment("[excited] "), len("[excited] "))

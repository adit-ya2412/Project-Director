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
    split_batched_alignment,
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

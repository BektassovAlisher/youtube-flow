"""Joins MP3 files frame by frame, without decoding or re-encoding.

ElevenLabs returns every line as its own MP3 (44.1 kHz, CBR). Gluing the frames keeps the original quality
and takes microseconds; the only care needed is to drop ID3 tags and the per-file Xing/Info header frame,
otherwise players take the duration of the first piece for the whole file."""

# Layer III bitrates (kbit/s) by bitrate index
_BITRATES_V1 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_BITRATES_V2 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_SAMPLE_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _payload_bounds(data: bytes) -> tuple[int, int]:
    start, end = 0, len(data)
    while data[start:start + 3] == b"ID3" and start + 10 <= end:  # ID3v2, possibly several
        size = (data[start + 6] << 21) | (data[start + 7] << 14) | (data[start + 8] << 7) | data[start + 9]
        footer = 10 if data[start + 5] & 0x10 else 0
        start += 10 + size + footer
    if end - start >= 128 and data[end - 128:end - 125] == b"TAG":  # ID3v1
        end -= 128
    if end - start >= 32 and data[end - 32:end - 24] == b"APETAGEX":  # APEv2 footer
        size = int.from_bytes(data[end - 20:end - 16], "little")
        end = max(start, end - size - (32 if data[end - 32 + 23] & 0x80 else 0))
    return start, end


def _frame(data: bytes, i: int, end: int):
    """(length, version, mono) of the Layer III frame at i, or None if there is no valid header there."""
    if i + 4 > end or data[i] != 0xFF or data[i + 1] & 0xE0 != 0xE0:
        return None
    version = (data[i + 1] >> 3) & 0b11  # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
    layer = (data[i + 1] >> 1) & 0b11  # 1 = Layer III
    bitrate_index = data[i + 2] >> 4
    rate_index = (data[i + 2] >> 2) & 0b11
    if version == 1 or layer != 1 or bitrate_index in (0, 15) or rate_index == 3:
        return None
    bitrate = (_BITRATES_V1 if version == 3 else _BITRATES_V2)[bitrate_index] * 1000
    rate = _SAMPLE_RATES[version][rate_index]
    padding = (data[i + 2] >> 1) & 1
    length = (144 if version == 3 else 72) * bitrate // rate + padding
    mono = (data[i + 3] >> 6) == 0b11
    return length, version, mono


def _is_info_frame(data: bytes, i: int, version: int, mono: bool) -> bool:
    side_info = (17 if mono else 32) if version == 3 else (9 if mono else 17)
    tag = data[i + 4 + side_info:i + 8 + side_info]
    return tag in (b"Xing", b"Info") or data[i + 36:i + 40] == b"VBRI"


def audio_frames(data: bytes) -> bytes:
    """The audio frames of one MP3 file, without tags and without the Xing/Info header frame."""
    start, end = _payload_bounds(data)
    out = bytearray()
    i, first = start, True
    while i < end:
        frame = _frame(data, i, end)
        if frame is None:
            i += 1  # garbage between frames: resync on the next header
            continue
        length, version, mono = frame
        if i + length > end:
            break  # truncated last frame
        if not (first and _is_info_frame(data, i, version, mono)):
            out += data[i:i + length]
        first = False
        i += length
    if not out:
        raise ValueError("no MP3 audio frames found")
    return bytes(out)


def concat(parts: list[bytes]) -> bytes:
    return b"".join(audio_frames(p) for p in parts)

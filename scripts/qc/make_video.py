#!/usr/bin/env python3
"""Recording compositor and event-driven audio mixer (needs ffmpeg, ffprobe and numpy).

Input: a folder written by the game's recording mode (reference/cpp/RecordMode.cpp): frames/frame_%06d.png,
record.json ({"fps": 30, ...}) and audio_events.jsonl (one JSON object per line: t, kind = sfx | music | musicvol |
loop | loopvol, name, vol, pitch, fade, action). Sounds are looked up as <name>.wav in the folders of env
UD_SOUND_DIRS (os.pathsep separated, relative paths are relative to the current directory).

  UD_SOUND_DIRS=assets/sfx:assets/music python3 scripts/qc/make_video.py render \
      --dir runs/video/seg_capture --out runs/video/seg_capture.mp4 --start 3 --end 21.5
  python3 scripts/qc/make_video.py cut \
      --out runs/video/rough_cut.mp4 --seg runs/video/a.mp4:0:8.5 --seg runs/video/b.mp4:2
  python3 scripts/qc/make_video.py selftest      # synthetic frames and sounds, needs no game

Audio is mixed as 48 kHz stereo float; pitch is implemented by resampling (speed and pitch change together).
render also keeps the trimmed PCM WAV; cut normalizes to -16 LUFS with loudnorm.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

RATE = 48000
CEILING = 10 ** (-1 / 20)


def search_dirs():
    return [Path(x) for x in os.environ.get('UD_SOUND_DIRS', '').split(os.pathsep) if x]


def warn(message):
    print(f'warning: {message}', file=sys.stderr, flush=True)


def run(args, *, capture=False):
    """No shell; on failure keep the ffmpeg diagnostics."""
    result = subprocess.run([str(x) for x in args], stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-12000:])
    return result.stdout if capture else result.stderr.decode(errors='replace')


def ffmpeg(*args, capture=False):
    return run(['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y', *args], capture=capture)


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                           '-of', 'json', path], capture=True))


def decode(path):
    raw = ffmpeg('-i', path, '-vn', '-ac', '2', '-ar', str(RATE),
                 '-f', 'f32le', 'pipe:1', capture=True)
    return np.frombuffer(raw, dtype='<f4').reshape(-1, 2)


def finite(value, label):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return value


@dataclass
class Envelope:
    """Linear envelope; a new command redirects from the current value, cancelling any unfinished fade."""
    points: list = field(default_factory=list)

    def value(self, t):
        return float(np.interp(t, [p[0] for p in self.points], [p[1] for p in self.points]))

    def target(self, t, value, fade=0):
        current = self.value(t)
        self.points = [p for p in self.points if p[0] < t]
        self.points.append((t, current))
        # Two points at the same time form a step, so an immediate stop does not turn into an early ramp.
        self.points.append((t + fade, value))

    def point(self, t, value):
        # loopvol is a sampled envelope: connect to the previous point instead of stepping.
        if self.points[-1][0] > t:
            current = self.value(t)
            self.points = [p for p in self.points if p[0] < t]
            self.points.append((t, current))
        self.points.append((t, value))

    def sample(self, times):
        return np.interp(times, [p[0] for p in self.points], [p[1] for p in self.points])


@dataclass
class Voice:
    name: str
    start: float
    volume: Envelope
    pitch: Envelope
    end: float = math.inf
    pitch_steps: bool = True

    def stop(self, t, fade):
        self.volume.target(t, 0, fade)
        self.end = min(self.end, t + fade)


def read_events(path):
    events = []
    if not path.exists():
        warn(f'no event log {path}, producing a silent track')
        return events
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                event['t'] = max(0.0, finite(event['t'], 't'))
                for key in ('vol', 'pitch', 'fade'):
                    if key in event:
                        event[key] = finite(event[key], key)
                if event.get('pitch', 1) <= 0 or event.get('fade', 0) < 0:
                    raise ValueError('pitch must be > 0 and fade must be >= 0')
                events.append(event)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f'{path}:{number}: {exc}') from exc
    return sorted(events, key=lambda e: e['t'])


def build_voices(events):
    """Turn state events into independent voices, keeping the old voice fading out on a music change."""
    voices, loops = [], {}
    music = None

    def create(e, start=None, fading=False, sampled_pitch=False):
        t = e['t'] if start is None else start
        vol, pitch = e.get('vol', 1), e.get('pitch', 1)
        fade = e.get('fade', 0) if fading else 0
        voice = Voice(e.get('name', ''), t, Envelope([(t, 0 if fade else vol)]),
                      Envelope([(t, pitch)]), pitch_steps=not sampled_pitch)
        if fade:
            voice.volume.target(t, vol, fade)
        voices.append(voice)
        return voice

    for e in events:
        t, kind, name = e['t'], e.get('kind'), e.get('name', '')
        fade = e.get('fade', 0)
        if kind == 'sfx':
            create(e)
        elif kind == 'music':
            if music is not None:
                music.stop(t, fade)
            music = create(e, fading=True) if name else None
        elif kind == 'musicvol':
            if music is not None and (not name or music.name == name):
                music.volume.target(t, e.get('vol', music.volume.value(t)), fade)
                music.pitch.points.append((t, e.get('pitch', music.pitch.value(t))))
        elif kind == 'loop':
            if e.get('action') == 'start':
                if name in loops:
                    loops.pop(name).stop(t, fade)
                loops[name] = create(e, fading=True, sampled_pitch=True)
            elif e.get('action') == 'stop':
                if name in loops:
                    loops.pop(name).stop(t, fade)
            else:
                warn(f'unknown loop action: {e.get("action")!r}')
        elif kind == 'loopvol':
            if name not in loops:
                # Recording started midway: the first loopvol is back-dated to t=0.
                loops[name] = create(e, start=0, sampled_pitch=True)
            voice = loops[name]
            voice.volume.point(t, e.get('vol', voice.volume.value(t)))
            voice.pitch.point(t, e.get('pitch', voice.pitch.value(t)))
        else:
            warn(f'ignoring unknown kind: {kind!r}')
    return voices


def mix(events, duration):
    """Integrate pitch per block to get source sample positions, interpolate, then sum."""
    result = np.zeros((round(duration * RATE), 2), dtype=np.float32)
    cache = {}
    for voice in build_voices(events):
        if voice.name not in cache:
            # name must be a bare asset name; the log may not reach files outside the search dirs.
            path = None
            if voice.name and Path(voice.name).name == voice.name:
                path = next((folder / f'{voice.name}.wav' for folder in search_dirs()
                             if (folder / f'{voice.name}.wav').is_file()), None)
            cache[voice.name] = decode(path) if path else None
            if path is None:
                warn(f'audio {voice.name!r} not found, skipping')
        source = cache[voice.name]
        if source is None or not len(source):
            continue
        begin = max(0, math.ceil(voice.start * RATE))
        end = min(len(result), math.ceil(min(duration, voice.end) * RATE))
        position = 0.0
        # Integrate from the voice start; trimming happens after mixing so a mid-clip cut stays aligned.
        for lo in range(begin, end, 65536):
            hi = min(end, lo + 65536)
            times = np.arange(lo, hi, dtype=np.float64) / RATE
            if voice.pitch_steps:
                pts = voice.pitch.points
                indexes = np.searchsorted([p[0] for p in pts], times, side='right') - 1
                pitches = np.array([p[1] for p in pts])[indexes]
            else:
                pitches = voice.pitch.sample(times)
            positions = position + np.cumsum(pitches) - pitches
            position += float(pitches.sum())
            if voice.name.endswith('_loop'):
                positions %= len(source)
                valid = np.ones(len(positions), dtype=bool)
            else:
                valid = positions < len(source)
            base = np.minimum(positions.astype(np.int64), len(source) - 1)
            following = (base + 1) % len(source) if voice.name.endswith('_loop') else np.minimum(base + 1, len(source) - 1)
            fraction = (positions - base)[:, None]
            samples = source[base] * (1 - fraction) + source[following] * fraction
            samples *= (voice.volume.sample(times) * valid)[:, None]
            result[lo:hi] += samples.astype(np.float32)
    return result


def dbfs(peak):
    return 20 * math.log10(peak) if peak > 0 else -math.inf


def save_mix(path, samples):
    peak = float(np.max(np.abs(samples))) if samples.size else 0
    gain = min(1.0, CEILING / peak) if peak else 1.0
    samples *= gain
    print(f'mix peak {dbfs(peak):.2f} dBFS; gain {dbfs(gain):.2f} dB; '
          f'output peak {dbfs(peak * gain):.2f} dBFS', flush=True)
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes((samples * 32767).round().astype('<i2').tobytes())
    # Standard EBU R128 measurement (gating and K-weighting); silence reports -inf.
    report = run(['ffmpeg', '-hide_banner', '-i', path, '-af', 'ebur128', '-f', 'null', '-'])
    values = re.findall(r'I:\s+(-?[\d.]+|-[Ii]nf) LUFS', report)
    print(f'integrated loudness: {values[-1] if values else "unmeasurable"} LUFS', flush=True)


def frame_info(directory):
    metadata = json.loads((directory / 'record.json').read_text())
    fps = finite(metadata['fps'], 'fps')
    if fps <= 0:
        raise ValueError('fps must be > 0')
    frames = {}
    for path in (directory / 'frames').glob('frame_*.png'):
        matched = re.fullmatch(r'frame_(\d+)\.png', path.name)
        if matched:
            frames[int(matched[1])] = path.resolve()
    if not frames:
        raise ValueError(f'{directory}/frames has no PNG frames')
    # Ignore the possibly stale metadata.frames; the highest index sets the real timeline length.
    count = max(frames) + 1
    return fps, frames, count


def prepare_frames(frames, count, destination):
    """image2 needs consecutive numbering; a missing frame reuses the previous one, and leading gaps reuse the first frame."""
    previous = frames[min(frames)]
    missing = 0
    for index in range(count):
        if index in frames:
            previous = frames[index]
        else:
            missing += 1
        target = destination / f'frame_{index:06d}.png'
        try:
            os.link(previous, target)
        except OSError:
            shutil.copyfile(previous, target)
    if missing:
        warn(f'filled {missing} missing frames (leading gaps use the first existing frame)')


def bounds(start, end, duration):
    start = finite(start, 'start')
    end = duration if end is None else finite(end, 'end')
    if start < 0 or end <= start or start >= duration or end > duration + 1e-5:
        raise ValueError(f'trim range {start}:{end} exceeds duration {duration:.6f}s or is empty')
    return start, min(end, duration)


def video_options():
    return ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k', '-ar', str(RATE), '-ac', '2', '-movflags', '+faststart']


def render(directory, output, start=0, end=None):
    directory, output = Path(directory).resolve(), Path(output).resolve()
    if output.suffix.lower() != '.mp4':
        raise ValueError('--out must end with .mp4')
    fps, frames, count = frame_info(directory)
    duration = count / fps
    start, end = bounds(start, end, duration)
    output.parent.mkdir(parents=True, exist_ok=True)
    audio = mix(read_events(directory / 'audio_events.jsonl'), duration)
    audio = audio[round(start * RATE):round(end * RATE)].copy()
    wav_path = output.with_suffix('.wav')
    save_mix(wav_path, audio)
    with tempfile.TemporaryDirectory(prefix='sg-video-frames-') as temporary:
        temp = Path(temporary).resolve()
        prepare_frames(frames, count, temp)
        filters = (f'trim=start={start}:end={end},setpts=PTS-STARTPTS,'
                   'scale=1920:1080:force_original_aspect_ratio=decrease,'
                   'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1')
        ffmpeg('-framerate', str(fps), '-i', temp / 'frame_%06d.png', '-i', wav_path,
               '-map', '0:v:0', '-map', '1:a:0', '-vf', filters, '-t', str(end - start), '-r', str(fps),
               *video_options(), output)
    print(f'wrote {output} ({end-start:.3f}s) and {wav_path}', flush=True)
    return end - start


def parse_segment(spec):
    """Parse :start[:end] from the right, so the path may contain colons."""
    parts = spec.rsplit(':', 2)
    if len(parts) == 1:
        return Path(spec).resolve(), 0.0, None
    try:
        if len(parts) == 3:
            return Path(parts[0]).resolve(), float(parts[1] or 0), float(parts[2]) if parts[2] else None
        return Path(parts[0]).resolve(), float(parts[1] or 0), None
    except ValueError as exc:
        raise ValueError(f'invalid --seg {spec!r}; format is path:start[:end]') from exc


def cut(segments, output):
    output = Path(output).resolve()
    if output.suffix.lower() != '.mp4':
        raise ValueError('--out must end with .mp4')
    output.parent.mkdir(parents=True, exist_ok=True)
    inputs, filters, durations = [], [], []
    for index, spec in enumerate(segments):
        path, start, end = parse_segment(spec)
        if path == output:
            raise ValueError('output must not overwrite an input segment')
        info = probe(path)
        duration = float(info['format']['duration'])
        start, end = bounds(start, end, duration)
        durations.append(end - start)
        inputs.extend(['-i', path])
        filters.append(f'[{index}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,'
                       'scale=1920:1080:force_original_aspect_ratio=decrease,'
                       'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,'
                       f'format=yuv420p,settb=AVTB[v{index}]')
        if any(s['codec_type'] == 'audio' for s in info['streams']):
            filters.append(f'[{index}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,'
                           f'aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,'
                           f'apad,atrim=duration={end-start}[a{index}]')
        else:
            filters.append(f'anullsrc=r={RATE}:cl=stereo,atrim=duration={end-start}[a{index}]')
    if not durations:
        raise ValueError('at least one --seg is required')
    if len(durations) > 1 and any(d <= 0.3 for d in durations):
        raise ValueError('crossfades require every segment to be longer than 0.3 s')
    # Inner segments must fit two non-overlapping 0.3 s fades, one at each end.
    if any(d < 0.6 for d in durations[1:-1]):
        raise ValueError('inner segments must be at least 0.6 s to fit two crossfades')
    v, a, elapsed = 'v0', 'a0', durations[0]
    for index in range(1, len(durations)):
        next_v, next_a = f'vx{index}', f'ax{index}'
        filters.append(f'[{v}][v{index}]xfade=transition=fade:duration=0.3:offset={elapsed-0.3}[{next_v}]')
        filters.append(f'[{a}][a{index}]acrossfade=d=0.3:c1=tri:c2=tri[{next_a}]')
        v, a = next_v, next_a
        elapsed += durations[index] - 0.3
    # Single-pass dynamic loudnorm; leave true-peak headroom for AAC encoding.
    filters.append(f'[{a}]loudnorm=I=-16:TP=-1.5:LRA=11,aresample={RATE}[normalized]')
    ffmpeg(*inputs, '-filter_complex_threads', '1', '-filter_complex', ';'.join(filters),
           '-map', f'[{v}]', '-map', '[normalized]', '-t', str(elapsed), '-r', '30',
           *video_options(), output)
    print(f'wrote rough cut {output} (target {elapsed:.3f}s, -16 LUFS)', flush=True)
    return elapsed


def check_output(path, expected):
    info = probe(path)
    actual = float(info['format']['duration'])
    if abs(actual - expected) >= 0.1:
        raise AssertionError(f'{path.name}: duration {actual:.4f}, expected {expected:.4f}')
    if not any(s['codec_type'] == 'audio' for s in info['streams']):
        raise AssertionError(f'{path.name}: missing audio track')
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    if (video['width'], video['height']) != (1920, 1080):
        raise AssertionError(f'{path.name}: wrong output size')
    peak = float(np.max(np.abs(decode(path))))
    if peak >= 1:
        raise AssertionError(f'{path.name}: peak {dbfs(peak):.2f} dBFS')
    print(f'checked {path.name}: {actual:.3f}s, audio OK, peak {dbfs(peak):.2f} dBFS', flush=True)


def selftest():
    """Synthetic sounds plus a small frame sequence with a gap; verifies render, trimming, mixing and rough cut."""
    temp = Path(tempfile.mkdtemp(prefix='ud-video-selftest-')).resolve()
    try:
        sounds = temp / 'sounds'
        sounds.mkdir()
        for name, hz, seconds in (('music_a', 220, 4), ('music_b', 330, 4), ('wind_loop', 110, 2), ('ambience_loop', 70, 2), ('click', 880, .1)):
            ffmpeg('-f', 'lavfi', '-i', f'sine=frequency={hz}:sample_rate={RATE}:duration={seconds}', '-ac', '2', sounds / f'{name}.wav')
        os.environ['UD_SOUND_DIRS'] = str(sounds)
        # Numeric assertions cover envelope edge cases that end-to-end encoding would not expose.
        envelope = Envelope([(0, 1)])
        envelope.target(1, 0)
        if envelope.value(.5) != 1 or envelope.value(1) != 0:
            raise AssertionError('an immediate stop must not fade early')
        envelope = Envelope([(0, 0)])
        envelope.target(0, 1, 2)
        envelope.target(1, 0, 1)
        if not np.allclose(envelope.sample([.5, 1, 1.5, 2]), [.25, .5, .25, 0]):
            raise AssertionError('an interrupted fade must continue from the current volume')
        implicit = build_voices([
            {'t': 1, 'kind': 'loopvol', 'name': 'wind_loop', 'vol': .2, 'pitch': 1},
            {'t': 2, 'kind': 'loopvol', 'name': 'wind_loop', 'vol': .4, 'pitch': 1.2},
        ])[0]
        if implicit.start != 0 or not np.isclose(implicit.volume.value(1.5), .3) or not np.isclose(implicit.pitch.value(1.5), 1.1):
            raise AssertionError('loop without start, or linear envelope, is wrong')
        capture = temp / 'capture'
        frames = capture / 'frames'
        frames.mkdir(parents=True)
        ffmpeg('-f', 'lavfi', '-i', 'color=c=red:s=640x360:r=30:d=1',
               '-f', 'lavfi', '-i', 'color=c=green:s=640x360:r=30:d=1',
               '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=30:d=1',
               '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
               '-map', '[v]', '-frames:v', '90', '-start_number', '0', frames / 'frame_%06d.png')
        (frames / 'frame_000017.png').unlink()
        (capture / 'record.json').write_text(json.dumps({'fps': 30, 'segment': 'selftest', 'frames': 999}))
        events = [
            {'t': 0, 'kind': 'music', 'name': 'music_a', 'fade': .2, 'vol': .55},
            {'t': .1, 'kind': 'loopvol', 'name': 'wind_loop', 'vol': .12, 'pitch': 1.1},
            {'t': .2, 'kind': 'loop', 'name': 'ambience_loop', 'action': 'start', 'fade': .2, 'vol': .2},
            {'t': .3, 'kind': 'sfx', 'name': 'click', 'vol': 1, 'pitch': 1.2},
            {'t': .4, 'kind': 'loopvol', 'name': 'wind_loop', 'vol': .25, 'pitch': .9},
            {'t': .8, 'kind': 'musicvol', 'name': 'music_a', 'fade': .4, 'vol': .4, 'pitch': 1.07},
            {'t': 1.2, 'kind': 'music', 'name': 'music_b', 'fade': .3, 'vol': .5},
            {'t': 1.4, 'kind': 'loop', 'name': 'ambience_loop', 'action': 'stop', 'fade': .3},
            {'t': 1.6, 'kind': 'loop', 'name': 'wind_loop', 'action': 'stop', 'fade': .2},
            {'t': 2.4, 'kind': 'music', 'name': '', 'fade': .4, 'vol': 0},
            {'t': 2.7, 'kind': 'sfx', 'name': 'click', 'vol': 1, 'pitch': .8},
            {'t': 2.8, 'kind': 'unknown_selftest'},
            {'t': 2.8, 'kind': 'sfx', 'name': '__missing_selftest__'},
        ]
        (capture / 'audio_events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
        first, second, final = temp / 'a.mp4', temp / 'b.mp4', temp / 'cut.mp4'
        render(capture, first)
        render(capture, second, .5, 2.5)
        check_output(first, 3)
        check_output(second, 2)
        # The trimmed WAV must match the full mix sample for sample at the same position (peak protection is not triggered here).
        with wave.open(str(first.with_suffix('.wav'))) as wav:
            full = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').reshape(-1, 2)
        with wave.open(str(second.with_suffix('.wav'))) as wav:
            clipped = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').reshape(-1, 2)
        if not np.array_equal(full[RATE // 2:RATE * 5 // 2], clipped):
            raise AssertionError('trimmed audio timeline differs from the full recording')
        expected = cut([f'{first}:0:2.5', f'{second}:.25:'], final)
        check_output(final, expected)
        print('PASS: render / cut / frame filling / time alignment / audio track / peak', flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, AssertionError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr, flush=True)
        return 1
    finally:
        shutil.rmtree(str(temp))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    renderer = commands.add_parser('render', help='compose a frame sequence and event log into MP4 + WAV')
    renderer.add_argument('--dir', type=Path, required=True)
    renderer.add_argument('--out', type=Path, required=True)
    renderer.add_argument('--start', type=float, default=0)
    renderer.add_argument('--end', type=float)
    cutter = commands.add_parser('cut', help='rough cut with 0.3 s crossfades and loudness normalization')
    cutter.add_argument('--out', type=Path, required=True)
    cutter.add_argument('--seg', action='append', required=True)
    commands.add_parser('selftest', help='run an end-to-end self-test on temporary fake data')
    args = parser.parse_args()
    for executable in ('ffmpeg', 'ffprobe'):
        if shutil.which(executable) is None:
            parser.error(f'{executable} not found in PATH')
    try:
        if args.command == 'render':
            render(args.dir, args.out, args.start, args.end)
        elif args.command == 'cut':
            cut(args.seg, args.out)
        else:
            return selftest()
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

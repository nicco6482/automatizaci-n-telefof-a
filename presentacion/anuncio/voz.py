"""Narración y música del anuncio.

Genera cada frase de `dashboard/src/anuncio/guion.json` con edge-tts, mide su duración, compone una música
suave que baja de volumen cuando habla la voz y deja:
  - dashboard/public/anuncio/tiempos.json  (inicio y fin de cada escena y frase, para la animación)
  - dashboard/public/anuncio/narracion.mp3 (voz + música, para la web)
  - <salida>/mezcla.wav                     (voz + música, para el vídeo)

Uso: uv run --with edge-tts --with numpy python presentacion/anuncio/voz.py <carpeta_de_trabajo>
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts  # type: ignore[import-not-found]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
GUION = ROOT / "dashboard" / "src" / "anuncio" / "guion.json"
PUBLIC = ROOT / "dashboard" / "public" / "anuncio"
SR = 44100
GAP = 0.28


async def tts(text: str, voice: str, out: Path) -> None:
    if out.exists() and out.stat().st_size > 0:
        return
    await edge_tts.Communicate(text, voice, rate="+6%").save(str(out))


def decode(mp3: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    x = np.frombuffer(raw, dtype=np.float32).copy()
    on = np.flatnonzero(np.abs(x) > 0.012)
    if on.size:
        x = x[max(0, on[0] - int(0.03 * SR)) : on[-1] + int(0.08 * SR)]
    return x


def music(total: float, scenes: list[dict]) -> np.ndarray:
    n = int(total * SR)
    t = np.arange(n, dtype=np.float64) / SR
    bar = 2.4
    # La menor · Fa · Do · Sol
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [196.0, 261.63, 329.63], [196.0, 246.94, 293.66]]
    roots = [110.0, 87.31, 130.81, 98.0]
    out = np.zeros((2, n), dtype=np.float64)

    def start_of(sid: str) -> float:
        return next(s["start"] for s in scenes if s["id"] == sid)

    beat_on, beat_off = start_of("equipo"), start_of("cierre") + 6.0
    arp_on = start_of("problema")
    nbars = int(total / bar) + 1
    for b in range(nbars):
        t0 = b * bar
        i0, i1 = int(t0 * SR), min(n, int((t0 + bar + 0.9) * SR))
        if i0 >= n:
            break
        tt = t[i0:i1] - t0
        env = np.minimum(1, tt / 0.5) * np.clip((bar + 0.9 - tt) / 0.9, 0, 1)
        ch = chords[b % 4]
        for k, f in enumerate(ch):
            for side, det in ((0, 0.997), (1, 1.003)):
                ff = f * det
                w = np.sin(2 * np.pi * ff * tt + k) + 0.45 * np.sin(4 * np.pi * ff * tt) + 0.18 * np.sin(6 * np.pi * ff * tt)
                out[side, i0:i1] += 0.05 * env * w
        # bajo
        r = roots[b % 4]
        out[:, i0:i1] += 0.10 * env * np.sin(2 * np.pi * r * tt)
        # arpegio en corcheas
        if t0 >= arp_on - 0.01:
            notes = [ch[0] * 2, ch[1] * 2, ch[2] * 2, ch[1] * 2, ch[0] * 4, ch[2] * 2, ch[1] * 2, ch[2] * 2]
            for j, f in enumerate(notes):
                s0 = t0 + j * bar / 8
                a0, a1 = int(s0 * SR), min(n, int((s0 + 0.6) * SR))
                if a0 >= n:
                    break
                u = t[a0:a1] - s0
                pl = np.exp(-u * 7) * (np.sin(2 * np.pi * f * u) + 0.25 * np.sin(4 * np.pi * f * u))
                pan = 0.35 if j % 2 else 0.65
                out[0, a0:a1] += 0.045 * pan * pl
                out[1, a0:a1] += 0.045 * (1 - pan) * pl
        # pulso suave (bombo y platillo)
        if beat_on <= t0 < beat_off:
            for q in range(4):
                s0 = t0 + q * bar / 4
                a0, a1 = int(s0 * SR), min(n, int((s0 + 0.25) * SR))
                if a0 >= n:
                    break
                u = t[a0:a1] - s0
                kick = np.sin(2 * np.pi * (48 * u + 40 * (1 - np.exp(-u * 30)) / 30 * 1.0)) * np.exp(-u * 16)
                out[:, a0:a1] += 0.16 * kick
            rng = np.random.default_rng(b)
            for q in range(8):
                s0 = t0 + q * bar / 8 + bar / 16
                a0, a1 = int(s0 * SR), min(n, int((s0 + 0.05) * SR))
                if a0 >= n:
                    break
                u = t[a0:a1] - s0
                noise = np.diff(rng.standard_normal(a1 - a0 + 1))
                out[:, a0:a1] += 0.010 * noise * np.exp(-u * 70)
    # eco con rebote izquierda-derecha
    d = int(0.36 * SR)
    wet = np.zeros_like(out)
    wet[0, d:] += out[1, :-d] * 0.32
    wet[1, d:] += out[0, :-d] * 0.32
    wet[0, 2 * d :] += out[0, : -2 * d] * 0.16
    wet[1, 2 * d :] += out[1, : -2 * d] * 0.16
    out += wet
    # entrada y salida
    fade_in = np.minimum(1, t / 2.0)
    fade_out = np.clip((total - t) / 4.0, 0, 1)
    out *= fade_in * fade_out
    return out / (np.abs(out).max() + 1e-9) * 0.5


def main() -> None:
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "anuncio_tmp").resolve()
    (work / "lineas").mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    guion = json.loads(GUION.read_text(encoding="utf-8"))
    voice = guion["voz"]

    jobs = []
    for s in guion["escenas"]:
        for i, ln in enumerate(s["lineas"]):
            jobs.append(tts(ln.get("voz", ln["texto"]), voice, work / "lineas" / f"{s['id']}_{i:02d}.mp3"))

    async def run_all() -> None:
        for k in range(0, len(jobs), 6):
            await asyncio.gather(*jobs[k : k + 6])

    asyncio.run(run_all())

    clips: list[tuple[float, np.ndarray]] = []
    scenes = []
    t = 0.0
    for s in guion["escenas"]:
        start = t
        t += s.get("pre", 0.4)
        lines = []
        for i, _ in enumerate(s["lineas"]):
            x = decode(work / "lineas" / f"{s['id']}_{i:02d}.mp3")
            lines.append({"start": round(t, 3), "end": round(t + len(x) / SR, 3)})
            clips.append((t, x))
            t += len(x) / SR + GAP
        t += s.get("post", 0.5) - GAP
        scenes.append({"id": s["id"], "start": round(start, 3), "end": round(t, 3), "lineas": lines})
    total = round(t, 3)

    voz = np.zeros(int(total * SR) + SR)
    for t0, x in clips:
        i0 = int(t0 * SR)
        voz[i0 : i0 + len(x)] += x
    voz = voz[: int(total * SR)]
    voz = voz / (np.abs(voz).max() + 1e-9) * 0.92

    mus = music(total, scenes)
    # la música baja cuando habla la voz
    act = (np.abs(voz) > 0.02).astype(np.float64)
    k = int(0.35 * SR)
    c = np.concatenate([[0.0], np.cumsum(act)])
    idx = np.arange(len(act))
    lo, hi = np.clip(idx - k // 2, 0, len(act)), np.clip(idx + k // 2, 0, len(act))
    act = (c[hi] - c[lo]) / k
    duck = 1 - 0.6 * np.clip(act * 3, 0, 1)
    mix = mus * duck * 0.55 + voz[None, :] * 0.9
    mix = mix / max(1.0, float(np.abs(mix).max()) / 0.98)

    wav = work / "mezcla.wav"
    pcm = (mix.T * 32767).astype("<i2").tobytes()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "-", str(wav)],
        input=pcm, check=True,
    )
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "128k", str(PUBLIC / "narracion.mp3")], check=True)
    (PUBLIC / "tiempos.json").write_text(json.dumps({"total": total, "escenas": scenes}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total {total:.1f} s · {len(clips)} frases · {wav}")


if __name__ == "__main__":
    main()

"""Entry point Musicozie: menjalankan pipeline Vision/Logic/Audio + dashboard web."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import config
from pipeline import SharedState, start_pipeline


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="musicozie", description="Instrumen virtual berbasis gestur jari"
    )
    p.add_argument(
        "--camera",
        type=int,
        default=config.CAMERA_INDEX,
        help="index kamera (default 0)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=config.PORT,
        help=f"port dashboard (default {config.PORT})",
    )
    p.add_argument(
        "--headless", action="store_true", help="tanpa dashboard/server web"
    )
    p.add_argument(
        "--soundfont",
        type=Path,
        default=config.SOUNDFONT_PATH,
        help="path file .sf2",
    )
    return p.parse_args(argv)


def shutdown(state: SharedState, threads: list, engine, server=None) -> None:
    state.stop_event.set()
    if server is not None:
        server.stop()
    for t in threads:
        t.join(timeout=3)
    if engine is not None:
        engine.stop()


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.soundfont.exists():
        print(
            f"ERROR: SoundFont tidak ditemukan: {args.soundfont}\nGunakan --soundfont <path.sf2>.",
            file=sys.stderr,
        )
        return 1

    state = SharedState()
    try:
        # require_camera diset False agar tidak crash di cloud server yang tidak punya kamera
        threads, engine = start_pipeline(
            state,
            args.camera,
            want_video=not args.headless,
            soundfont=args.soundfont,
            require_camera=False,
        )
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: gagal memulai audio/pipeline: {e}", file=sys.stderr)
        return 1

    server = None
    if not args.headless:
        from server import ServerThread

        server = ServerThread(state, args.port)
        server.start()
        print(f"Dashboard berjalan pada http://{config.HOST}:{args.port}")

    print("Musicozie berjalan. Ctrl+C untuk berhenti.")

    return_code = 0
    try:
        last_print = 0.0
        while not state.stop_event.is_set():
            time.sleep(0.2)
            vision_alive = any(
                t.is_alive() for t in threads if t.name == "vision"
            )
            if server is not None and not server.is_alive():
                print(
                    f"ERROR: dashboard gagal start di port {args.port}.",
                    file=sys.stderr,
                )
                return_code = 1
                break
            if args.headless and not vision_alive:
                print(
                    f"ERROR: {state.snapshot()['message'] or 'vision berhenti'}",
                    file=sys.stderr,
                )
                break
            if args.headless and time.monotonic() - last_print > 2.0:
                last_print = time.monotonic()
                s = state.snapshot()
                print(
                    f"[{s['status']}] fps={s['fps']} latensi~{s['latency_ms']}ms "
                    f"{s['mode_label']} nada={(s['note'] or {}).get('label', '-')}"
                )
    except KeyboardInterrupt:
        print("\nMenghentikan Musicozie...")
    finally:
        shutdown(state, threads, engine, server)
    return return_code


if __name__ == "__main__":
    sys.exit(main())
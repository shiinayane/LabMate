"""Interactive multi-object demo: chat with the running sim (docs/11).

    ./scripts/labrun python scripts/interactive.py \
        --objects benchmark/demo/chemistry_demo.json [--headless]

Brings the sim up ONCE with ALL configured objects placed + visible, then a blocking REPL: type an
instruction, the robot picks the grounded object; ambiguous -> it ASKs (answer at the prompt); unsafe
-> it REFUSEs and nothing runs. Drop ``--headless`` to see the window on a VNC desktop. Robot motion
is wired for ``pick`` only (docs/11). Commands: ``reset`` (re-home + re-show), ``quit``/``exit``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from labmate.interactive import run_turn                     # noqa: E402
from labmate.parser.rule_parser import RuleParser            # noqa: E402
from labmate.planner.loop import PlannerConfig               # noqa: E402
from labmate.trace import render_step                        # noqa: E402


def _load_objects(path: str | None):
    if not path:
        return None, None
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        return data.get("objects"), data.get("scene_flags")
    return data, None


def main() -> None:
    ap = argparse.ArgumentParser(description="LabMate interactive multi-object demo.")
    ap.add_argument("--scene", default="chemistry_lab_multi")
    ap.add_argument("--objects", default=str(REPO / "benchmark" / "demo" / "chemistry_demo.json"))
    ap.add_argument("--planner", default=str(REPO / "configs" / "planners" / "scene_grounded.yaml"))
    ap.add_argument("--out", default=str(REPO / "outputs" / "labmate" / "_interactive"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--verbose-sim", action="store_true", help="don't suppress Isaac/Kit logs")
    ap.add_argument("--no-runtime-stop", action="store_true",
                    help="disable the B1b runtime disturbance monitor")
    args = ap.parse_args()

    cfg = PlannerConfig.load(args.planner)
    scene_spec = json.loads((REPO / "benchmark" / "scenes" / f"{args.scene}.json").read_text())
    objects, scene_flags = _load_objects(args.objects)
    parser = RuleParser()

    from labmate.labutopia.adapter import SimSession
    from labmate.skills.executor import SimBackend

    session = SimSession(scene_spec, run_dir=str(Path(args.out) / "labutopia"), headless=args.headless,
                         objects=objects, scene_flags=scene_flags, multi_visible=True,
                         quiet=not args.verbose_sim,
                         monitor_disturbance=not args.no_runtime_stop).start()
    try:
        backend = SimBackend(session)
        names = [o["name"] for o in session.objects if o.get("pose")]
        print(f"\n=== LabMate interactive demo ({cfg.name}) ===", flush=True)
        print(f"objects in scene: {', '.join(names)}", flush=True)
        print("type an instruction (e.g. 'pick the left conical bottle'); 'reset' / 'quit'.\n", flush=True)

        ask_fn = lambda q: input(f"  ↳ {q}\n  > ").strip()
        on_step = lambda st: print(render_step(st), flush=True)

        while True:
            try:
                instr = input("\n> ").strip()
            except EOFError:
                break
            if not instr:
                continue
            if instr in ("quit", "exit"):
                break
            if instr == "reset":
                backend._held = None
                session.show_all_objects()
                session.pump()
                print("(reset: gripper cleared, objects re-shown)", flush=True)
                continue
            res = run_turn(instr, cfg, backend, parser, ask_fn, on_step=on_step)
            if res.stopped:                           # B1b: runtime monitor halted the motion
                print(f"⚠ {res.reason} — retry, pick another, or move it (then 'reset').", flush=True)
            kind = res.decisions[-1].kind if res.decisions else "?"
            print(f"=> {kind}  executed={res.executed} held={res.held} "
                  f"resolved={res.resolved_target}" + (f" reason={res.reason}" if res.reason else ""),
                  flush=True)
            session.pump(30)                              # settle + render between commands
    except Exception:
        import traceback
        traceback.print_exc()                            # before close(): hard-exit swallows it
        sys.stdout.flush()
    finally:
        session.close()


if __name__ == "__main__":
    main()

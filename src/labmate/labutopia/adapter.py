"""LabUtopia / Isaac Sim adapter — the ONLY module that imports Isaac Sim or LabUtopia.

Everything is **lazy-imported inside methods** so ``import labmate`` and the sim-free tests run on a
plain machine (docs/08/10). We reuse LabUtopia's proven ``main.py`` orchestration — factories +
scripted FSM controllers — rather than reimplementing manipulation.

W1 scope: bring the sim up once, load a scene, and drive ONE scripted controller (e.g. ``pick``) to
completion, reading back enough sim GT to build the minimal scene graph the predicates need. Because
LabUtopia exposes no "object held" flag, W1 derives ``held`` from the controller's own success
(object lifted ≥ 0.1 m — its ``_check_success``); a geometric held-check is a W2 refinement.
"""

from __future__ import annotations

import contextlib
import copy
import os
import sys
from pathlib import Path
from typing import Optional

from ..scene.scene_graph import SceneGraph


@contextlib.contextmanager
def _redirect_fds_to(path: str):
    """Redirect OS-level stdout+stderr (fd 1/2) to a file, then restore.

    Isaac/Kit prints its startup banner + RMPFlow config via C-level stdio straight to fd 1, which a
    Python ``sys.stdout`` swap cannot catch. We dup the fds to a log file for the duration so the
    interactive REPL stays clean; the noise is still on disk for debugging.
    """
    def _libc_flush():
        # flush C-level stdio so buffered Kit output lands in the sink, not on the restored terminal
        try:
            import ctypes
            ctypes.CDLL(None).fflush(None)
        except Exception:
            pass

    sys.stdout.flush()
    sys.stderr.flush()
    _libc_flush()
    save_out, save_err = os.dup(1), os.dup(2)
    sink = open(path, "a")
    try:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        _libc_flush()
        os.dup2(save_out, 1)
        os.dup2(save_err, 2)
        os.close(save_out)
        os.close(save_err)
        sink.close()

# src/labutopia (sibling of src/labmate); also on sys.path via the venv .pth, set here defensively.
LABUTOPIA_DIR = Path(__file__).resolve().parents[2] / "labutopia"

# Which world axis (and sign) is the robot's LEFT. +1 => larger y = left (assumed Franka convention).
# VERIFY on the first multi-object run and flip if needed (see docs/11 / W2 plan risks).
LEFT_SIGN = 1

# Skills whose controller needs a NON-default LabUtopia task built from its own config (approach B,
# docs/12): controller -> (task_type, config-file-stem). `pick` uses the scene's default task.
_SKILL_TASK = {
    "open": ("openclose", "level1_open_drawer"),
    "close": ("openclose", "level1_open_drawer"),
}


def _patch_omegaconf_resolver_once() -> None:
    """Force ``OmegaConf.register_new_resolver(..., replace=True)`` process-wide.

    LabUtopia's ``BaseController.__init__`` registers an ``eval`` resolver WITHOUT ``replace=True``
    (``controllers/base_controller.py``), so the **2nd** controller built in one process raises
    ``ValueError: resolver 'eval' is already registered``. We create a fresh controller per skill, so
    any multi-skill sequence / retry would crash. We can't edit LabUtopia → make registration
    idempotent here. Applied once; respects an explicit ``replace`` if a caller passes one.
    """
    from omegaconf import OmegaConf
    if getattr(OmegaConf, "_labmate_resolver_patch", False):
        return
    _orig = OmegaConf.register_new_resolver

    def _reg(name, resolver, *args, **kwargs):
        kwargs.setdefault("replace", True)
        return _orig(name, resolver, *args, **kwargs)

    OmegaConf.register_new_resolver = staticmethod(_reg)
    OmegaConf._labmate_resolver_patch = True


class SimSession:
    """Owns the Isaac Sim lifecycle + a LabUtopia task/controller for one scene.

    Create once per process (SimulationApp is a singleton). ``scene_spec`` is the parsed
    ``benchmark/scenes/<scene>.json``; ``objects`` is the per-episode object list (name, usd_path,
    category, pose, flags) — from the episode's ``init_overrides`` (W2) or derived from the scene map
    (W1). Objects with an explicit ``pose`` are placed there (degenerate position_range) and become
    selectable pick targets via ``select``.
    """

    def __init__(self, scene_spec: dict, run_dir: str, headless: bool = True,
                 objects: Optional[list[dict]] = None, scene_flags: Optional[list[str]] = None,
                 multi_visible: bool = False, quiet: bool = False,
                 monitor_disturbance: bool = False, disturb_threshold: float = 0.05,
                 settle_frames: int = 30):
        self.scene_spec = scene_spec
        self.run_dir = run_dir
        self.headless = headless
        self.quiet = quiet                            # suppress Isaac/Kit log spam (carb/omni.log)
        self.objects = objects if objects is not None else self._objects_from_scene_spec(scene_spec)
        self._objects0 = copy.deepcopy(self.objects)  # initial layout, restored by reset_scene()
        self.scene_flags = list(scene_flags or [])
        # interactive demo: keep ALL configured objects placed + visible (LabUtopia normally hides
        # every object except current_obj_idx). Re-applied after each task.reset().
        self.multi_visible = multi_visible
        # B1b runtime safety: stop a skill the moment a NON-target object is disturbed (docs/12).
        self.monitor_disturbance = monitor_disturbance
        self.disturb_threshold = disturb_threshold
        self.settle_frames = settle_frames
        self._target_name: Optional[str] = None       # grasp target (set by select), excluded from monitor
        self._last_stop: Optional[dict] = None         # {"object", "disp"} of the last runtime stop
        self.robot_xy = [0.0, 0.0]
        self._index_by_name: dict[str, int] = {}
        self._app = None
        self._world = None
        self._robot = None
        self._stage = None
        self._task = None
        self._tasks: dict = {}                        # task_type -> (task, cfg) (approach B, lazy)
        self._default_task_type = None                # the scene's task (pick); set in _start_impl
        self._controller = None
        self._objutils = None
        self._cfg = None

    @staticmethod
    def _objects_from_scene_spec(scene_spec: dict) -> list[dict]:
        return [
            {"name": meta["name"], "usd_path": usd, "category": meta["category"],
             "flags": meta.get("flags", {}), "pose": meta.get("pose")}
            for usd, meta in scene_spec.get("objects", {}).items()
        ]

    # ---- lifecycle ------------------------------------------------------
    def _quiet_io(self):
        """Redirect Isaac's fd-level log spam to ``<run_dir>/sim.log`` when ``quiet`` (else no-op)."""
        if not self.quiet:
            return contextlib.nullcontext()
        os.makedirs(self.run_dir, exist_ok=True)
        return _redirect_fds_to(str(Path(self.run_dir) / "sim.log"))

    def start(self) -> "SimSession":
        if str(LABUTOPIA_DIR) not in sys.path:
            sys.path.insert(0, str(LABUTOPIA_DIR))
        os.makedirs(self.run_dir, exist_ok=True)
        with self._quiet_io():
            self._start_impl()
        return self

    def _start_impl(self) -> None:
        from isaacsim import SimulationApp
        extra_args = ["--/rtx/raytracing/fractionalCutoutOpacity=true"]
        if self.quiet:
            # drop Kit/carb warning+info spam to stderr (our own stdout prints are unaffected)
            extra_args += ["--/log/level=error", "--/log/outputStreamLevel=error",
                           "--/log/fileLogLevel=error"]
        self._app = SimulationApp({"headless": self.headless, "extra_args": extra_args})

        if self.quiet:
            try:
                import carb
                _s = carb.settings.get_settings()
                _s.set_string("/log/level", "error")
                _s.set_string("/log/outputStreamLevel", "error")
            except Exception:
                pass

        import numpy as np
        import omni
        from isaacsim.core.api import World
        from isaacsim.core.utils import extensions
        from isaacsim.core.utils.stage import add_reference_to_stage
        from omegaconf import OmegaConf

        from factories.controller_factory import create_controller
        from factories.robot_factory import create_robot
        from factories.task_factory import create_task
        from utils.object_utils import ObjectUtils

        extensions.enable_extension("omni.physx.bundle")

        _patch_omegaconf_resolver_once()              # make per-skill controller creation safe (#1)
        cfg = OmegaConf.load(str(LABUTOPIA_DIR / "config" / f"{self.scene_spec['labutopia_config']}.yaml"))
        cfg.max_episodes = 1
        cfg.collector.type = "mock"                   # W3: executor drives the scripted FSM, no HDF5
        cfg.multi_run.run_dir = self.run_dir          # concrete path: avoids hydra ${now:} resolver
        os.makedirs(self.run_dir, exist_ok=True)
        self.robot_xy = [float(cfg.robot.position[0]), float(cfg.robot.position[1])]

        # W2: rebind the task's objects to this episode's placed objects (degenerate position_range =
        # fixed pose). The candidate order defines current_obj_idx, used by select() to pick a target.
        # `fixed` objects (furniture, e.g. a drawer) are NOT placeable -> excluded (they keep their USD
        # pose; their own skill task references them, approach B).
        placed = [o for o in self.objects if o.get("pose") and o.get("usd_path") and not o.get("fixed")]
        if placed:
            cfg.task.obj_paths = [
                {"path": o["usd_path"],
                 "position_range": {"x": [o["pose"][0]] * 2,
                                    "y": [o["pose"][1]] * 2,
                                    "z": [o["pose"][2]] * 2}}
                for o in placed
            ]
            self._index_by_name = {o["name"]: i for i, o in enumerate(placed)}
        self._cfg = cfg

        self._world = World(stage_units_in_meters=1.0, physics_prim_path="/physicsScene", backend="numpy")
        self._robot = create_robot(cfg.robot.type, position=np.array(cfg.robot.position))
        self._stage = omni.usd.get_context().get_stage()
        add_reference_to_stage(
            usd_path=os.path.abspath(str(LABUTOPIA_DIR / cfg.usd_path)), prim_path="/World"
        )
        self._objutils = ObjectUtils.get_instance(self._stage)
        self._task = create_task(cfg.task_type, cfg=cfg, world=self._world, stage=self._stage, robot=self._robot)
        self._default_task_type = cfg.task_type        # the scene's task (pick); approach-B cache key
        self._tasks[cfg.task_type] = (self._task, cfg)  # task_type -> (task, cfg)
        # Controllers are created FRESH per skill in run_skill (their episode_count is cumulative, so
        # one controller cannot be reused for a sequence/retry — Explore finding, docs/11).
        if self.multi_visible:
            self.show_all_objects()                   # interactive demo: co-present scene at startup
            self.pump()

    def close(self) -> None:
        with self._quiet_io():
            if self._controller is not None:
                try:
                    self._controller.close()
                except Exception:
                    pass
            if self._app is not None:
                self._app.close()

    # ---- execution ------------------------------------------------------
    def _ensure_task(self, controller_type: Optional[str]):
        """The (task, cfg) matching this skill's controller — built once on the same world (approach B).

        Most controllers use the scene's default task (pick). Controllers in ``_SKILL_TASK`` (e.g.
        ``open``) need their own LabUtopia task built from that skill's config, on the SAME
        world/stage/robot/USD (verified feasible). Cached by task_type.
        """
        name = controller_type or self._cfg.controller_type
        task_type, cfg_file = _SKILL_TASK.get(name, (self._default_task_type, None))
        if task_type in self._tasks:
            return self._tasks[task_type]
        from omegaconf import OmegaConf
        from factories.task_factory import create_task
        scfg = OmegaConf.load(str(LABUTOPIA_DIR / "config" / f"{cfg_file}.yaml"))
        scfg.collector.type = "mock"
        scfg.multi_run.run_dir = self.run_dir
        task = create_task(task_type, cfg=scfg, world=self._world, stage=self._stage, robot=self._robot)
        self._tasks[task_type] = (task, scfg)
        return task, scfg

    def run_skill(self, controller_type: Optional[str] = None) -> bool:
        """Drive ONE scripted skill to completion and return its success.

        A **fresh controller is created per call** (its episode_count is cumulative, so a controller
        can't be reused for a sequence/retry — Explore finding). `task.reset()` hands the robot back to
        home between skills. Terminates on the controller's own `done`, NOT on episode_num — so this
        works for multi-skill sequences and retries (W3). We do NOT call `task.on_task_complete` here:
        its index/material cycling would drift `current_obj_idx` away from what `select()` pinned (#3).
        """
        with self._quiet_io():                        # keep Isaac/RMPFlow stdio out of the REPL
            return self._run_skill_impl(controller_type)

    def _run_skill_impl(self, controller_type: Optional[str]) -> bool:
        from factories.controller_factory import create_controller

        task, cfg = self._ensure_task(controller_type)   # approach B: per-skill task + its cfg
        self._task = task
        world, robot, app = self._world, self._robot, self._app
        controller = create_controller(controller_type or cfg.controller_type, cfg=cfg, robot=robot)
        self._controller = controller                 # tracked so close() can clean up (#4)
        cap = int(getattr(cfg.task, "max_steps", 800)) + 200   # hard frame cap: never hang (#2)
        self._last_stop = None
        monitor = self._make_monitor()                # B1b: None unless monitor_disturbance
        try:
            steps = 0
            task.reset()
            if self.multi_visible:
                self.show_all_objects()               # reset() re-hid the neighbours — show them again
            while app.is_running():
                world.step(render=True)
                if not world.is_playing():
                    continue
                state = task.step()
                if state is None:
                    continue
                # NOTE: task.step() can advance current_obj_idx if a skill overruns the task's own
                # max_steps (check_frame_limits -> on_task_complete). Harmless here: select() re-pins
                # it before every run_skill, and the only path that ran without select (executor.run)
                # was removed. We deliberately do NOT stop on reset_needed — that would preempt the B1b
                # disturbance monitor on a stuck-and-flailing skill (audit-2).
                if monitor is not None:               # B1b runtime disturbance stop
                    pos = self._object_positions()
                    if not monitor.ready:
                        if steps >= self.settle_frames:   # arm once settled (>= so a short skip still arms)
                            monitor.set_baseline(pos)
                    else:
                        hit = monitor.update(pos)
                        if hit is not None:
                            self._last_stop = {"object": hit[0], "disp": hit[1]}
                            return False              # stop the skill, hand back to the human
                action, done, is_success = controller.step(state)
                if action is not None:
                    robot.get_articulation_controller().apply_action(action)
                if done:
                    return bool(is_success)
                steps += 1
                if steps > cap:                       # controller never reported done -> give up
                    return False
            return False
        finally:
            try:
                controller.close()
            except Exception:
                pass
            self._controller = None

    def _make_monitor(self):
        """A DisturbanceMonitor over the configured objects, or None when disabled (B1b)."""
        if not self.monitor_disturbance:
            return None
        from ..safety.runtime import DisturbanceMonitor
        return DisturbanceMonitor(self._target_name, self.disturb_threshold)

    def _object_positions(self) -> dict:
        """Current world centre of each configured object (physics-tracking, B1b monitor input)."""
        out: dict = {}
        for o in self.objects:
            path = o.get("usd_path")
            if not path:
                continue
            try:
                out[o["name"]] = [float(x) for x in self._objutils.get_geometry_center(object_path=path)]
            except Exception:
                out[o["name"]] = None
        return out

    def show_all_objects(self) -> None:
        """Place ALL configured objects at their declared poses and make them visible (demo).

        LabUtopia's ``place_objects_with_visibility_management`` keeps only ``current_obj_idx`` visible
        and teleports the rest 10 m away; for a co-present interactive scene we undo that. Visibility is
        set once and persists through the skill (controllers never touch it — Explore finding).
        """
        if self._stage is None or self._objutils is None:
            return
        import numpy as np
        from isaacsim.core.utils.prims import set_prim_visibility
        for o in self.objects:
            pose, path = o.get("pose"), o.get("usd_path")
            if not pose or not path or o.get("fixed"):    # never reposition furniture (drawer/door)
                continue
            prim = self._stage.GetPrimAtPath(path)
            if not prim.IsValid():
                continue
            self._objutils.set_object_position(object_path=path, position=np.array(pose, dtype=float))
            set_prim_visibility(prim, True)

    # ---- human scene edits (HRC: clear an obstacle, then re-run) --------
    ASIDE = [0.42, 0.40, 0.82]                        # staging corner (best-effort; `remove` is cleaner)

    def _spec(self, name: str) -> Optional[dict]:
        return next((o for o in self.objects if o.get("name") == name), None)

    def move_object(self, name: str, x: float, y: float, z: Optional[float] = None) -> list[float]:
        """Relocate an object in the live sim AND its declared pose, so grounding re-reads it (Path A).

        NOTE: the physical move only persists across the NEXT skill if ``multi_visible`` is on (each
        ``run_skill`` calls ``task.reset()`` which re-places objects from a frozen snapshot, then
        ``show_all_objects()`` re-applies our updated poses). The interactive demo uses
        ``multi_visible=True``; do not call this on a non-multi_visible session.
        """
        o = self._spec(name)
        if o is None or not o.get("usd_path"):
            raise KeyError(name)
        if z is None:
            z = float(o["pose"][2]) if o.get("pose") and len(o["pose"]) >= 3 else self.ASIDE[2]
        pose = [float(x), float(y), float(z)]
        import numpy as np
        self._objutils.set_object_position(object_path=o["usd_path"], position=np.array(pose))
        o["pose"] = pose                              # KEY: keep the declared-pose scene graph in sync
        self.pump(20)
        return pose

    def move_aside(self, name: str) -> list[float]:
        return self.move_object(name, self.ASIDE[0], self.ASIDE[1], self.ASIDE[2])

    def _restore_objects(self) -> None:
        """Restore the object set + poses + index to the initial layout (pure; undoes move/remove)."""
        self.objects = copy.deepcopy(self._objects0)
        placed = [o for o in self.objects if o.get("pose") and o.get("usd_path")]
        self._index_by_name = {o["name"]: i for i, o in enumerate(placed)}
        self._target_name = None
        self._last_stop = None

    def reset_scene(self) -> None:
        """Put every object back at its initial pose (incl. ones the human moved/removed)."""
        self._restore_objects()
        self.show_all_objects()                       # places all at restored poses + visible
        self.pump(20)

    def remove_object(self, name: str) -> None:
        """Take an object off the table: hide + teleport far, and drop it from the scene graph."""
        o = self._spec(name)
        if o is None:
            raise KeyError(name)
        path = o.get("usd_path")
        if path:
            import numpy as np
            from isaacsim.core.utils.prims import set_prim_visibility
            self._objutils.set_object_position(object_path=path, position=np.array([10.0, 10.0, 0.1]))
            prim = self._stage.GetPrimAtPath(path)
            if prim.IsValid():
                set_prim_visibility(prim, False)
        self.objects = [x for x in self.objects if x.get("name") != name]   # excluded from grounding/monitor
        self._index_by_name.pop(name, None)           # do NOT reindex (current_obj_idx is fixed)
        self.pump(10)

    def pump(self, frames: int = 60) -> None:
        """Idle-render N frames (keep the viewport alive between commands, let physics settle)."""
        if self._app is None or self._world is None:
            return
        with self._quiet_io():
            for _ in range(frames):
                if not self._app.is_running():
                    break
                self._world.step(render=True)

    def select(self, target_name: Optional[str]) -> None:
        """Point the task at the object the planner grounded to (W2 multi-object pick)."""
        self._target_name = target_name               # excluded from the B1b disturbance monitor
        if self._task is None or target_name is None:
            return
        idx = self._index_by_name.get(target_name)
        if idx is not None:
            self._task.current_obj_idx = idx

    # ---- scene graph ----------------------------------------------------
    def build_scene_graph(self, held: Optional[str] = None) -> SceneGraph:
        """Build the scene graph from this episode's objects (poses + flags) — relations computed.

        Poses come from the episode's ``init_overrides`` (declared GT, docs/08); if a spec has no
        pose we query ``ObjectUtils`` live as a fallback. Relations + left/right derive from poses.
        """
        specs = []
        for o in self.objects:
            pose = o.get("pose")
            if pose is None and o.get("usd_path") is not None:
                try:
                    pose = [float(x) for x in
                            self._objutils.get_geometry_center(object_path=o["usd_path"])]
                except Exception:
                    pose = None
            specs.append({
                "name": o["name"],
                "category": o["category"],
                "usd_path": o.get("usd_path"),
                "pose": list(pose) if pose is not None else None,
                "size": o.get("size"),
                "flags": o.get("flags", {}),
            })
        frame = {"robot_xy": self.robot_xy, "left_axis": "y", "left_sign": LEFT_SIGN}
        return SceneGraph.from_specs(specs, frame=frame, held=held, scene_flags=self.scene_flags)

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

import os
import sys
from pathlib import Path
from typing import Optional

from ..scene.scene_graph import SceneGraph

# src/labutopia (sibling of src/labmate); also on sys.path via the venv .pth, set here defensively.
LABUTOPIA_DIR = Path(__file__).resolve().parents[2] / "labutopia"

# Which world axis (and sign) is the robot's LEFT. +1 => larger y = left (assumed Franka convention).
# VERIFY on the first multi-object run and flip if needed (see docs/11 / W2 plan risks).
LEFT_SIGN = 1


class SimSession:
    """Owns the Isaac Sim lifecycle + a LabUtopia task/controller for one scene.

    Create once per process (SimulationApp is a singleton). ``scene_spec`` is the parsed
    ``benchmark/scenes/<scene>.json``; ``objects`` is the per-episode object list (name, usd_path,
    category, pose, flags) — from the episode's ``init_overrides`` (W2) or derived from the scene map
    (W1). Objects with an explicit ``pose`` are placed there (degenerate position_range) and become
    selectable pick targets via ``select``.
    """

    def __init__(self, scene_spec: dict, run_dir: str, headless: bool = True,
                 objects: Optional[list[dict]] = None):
        self.scene_spec = scene_spec
        self.run_dir = run_dir
        self.headless = headless
        self.objects = objects if objects is not None else self._objects_from_scene_spec(scene_spec)
        self.robot_xy = [0.0, 0.0]
        self._index_by_name: dict[str, int] = {}
        self._app = None
        self._world = None
        self._robot = None
        self._stage = None
        self._task = None
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
    def start(self) -> "SimSession":
        if str(LABUTOPIA_DIR) not in sys.path:
            sys.path.insert(0, str(LABUTOPIA_DIR))

        from isaacsim import SimulationApp
        self._app = SimulationApp(
            {"headless": self.headless,
             "extra_args": ["--/rtx/raytracing/fractionalCutoutOpacity=true"]}
        )

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

        cfg = OmegaConf.load(str(LABUTOPIA_DIR / "config" / f"{self.scene_spec['labutopia_config']}.yaml"))
        cfg.max_episodes = 1
        cfg.multi_run.run_dir = self.run_dir          # concrete path: avoids hydra ${now:} resolver
        os.makedirs(self.run_dir, exist_ok=True)
        self.robot_xy = [float(cfg.robot.position[0]), float(cfg.robot.position[1])]

        # W2: rebind the task's objects to this episode's placed objects (degenerate position_range =
        # fixed pose). The candidate order defines current_obj_idx, used by select() to pick a target.
        placed = [o for o in self.objects if o.get("pose") and o.get("usd_path")]
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
        self._controller = create_controller(cfg.controller_type, cfg=cfg, robot=self._robot)
        return self

    def close(self) -> None:
        if self._controller is not None:
            try:
                self._controller.close()
            except Exception:
                pass
        if self._app is not None:
            self._app.close()

    # ---- execution ------------------------------------------------------
    def run_skill(self) -> bool:
        """Drive the configured scripted controller for one episode; return its success.

        Mirrors LabUtopia ``main.py`` (sans cameras/video). One "episode" == one skill execution.
        """
        task, controller, world, robot, app = (
            self._task, self._controller, self._world, self._robot, self._app
        )
        last_success = False
        task.reset()
        while app.is_running():
            world.step(render=True)
            if world.is_stopped():
                controller.reset_needed = True
            if not world.is_playing():
                continue
            if controller.need_reset() or task.need_reset():
                controller.reset()
                if controller.episode_num() >= 1:
                    break
                task.reset()
                continue
            state = task.step()
            if state is None:
                continue
            action, done, is_success = controller.step(state)
            if action is not None:
                robot.get_articulation_controller().apply_action(action)
            if done:
                last_success = bool(is_success)
                task.on_task_complete(is_success)
                continue
        return last_success

    def select(self, target_name: Optional[str]) -> None:
        """Point the task at the object the planner grounded to (W2 multi-object pick)."""
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
        return SceneGraph.from_specs(specs, frame=frame, held=held)

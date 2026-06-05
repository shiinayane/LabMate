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

from ..scene.scene_graph import ObjectFlags, SceneGraph, SceneObject

# src/labutopia (sibling of src/labmate); also on sys.path via the venv .pth, set here defensively.
LABUTOPIA_DIR = Path(__file__).resolve().parents[2] / "labutopia"


class SimSession:
    """Owns the Isaac Sim lifecycle + a LabUtopia task/controller for one scene.

    Create once per process (SimulationApp is a singleton). ``scene_spec`` is the parsed
    ``benchmark/scenes/<scene>.json``.
    """

    def __init__(self, scene_spec: dict, run_dir: str, headless: bool = True):
        self.scene_spec = scene_spec
        self.run_dir = run_dir
        self.headless = headless
        self._app = None
        self._world = None
        self._robot = None
        self._stage = None
        self._task = None
        self._controller = None
        self._objutils = None
        self._cfg = None

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

    # ---- scene graph ----------------------------------------------------
    def build_scene_graph(self, held: Optional[str] = None) -> SceneGraph:
        """Construct the minimal scene graph from the annotation map + ObjectUtils positions."""
        objects = []
        for usd_path, meta in self.scene_spec.get("objects", {}).items():
            pose = None
            try:
                pose = [float(x) for x in self._objutils.get_geometry_center(object_path=usd_path)]
            except Exception:
                pose = None
            objects.append(SceneObject(
                name=meta["name"],
                category=meta["category"],
                usd_path=usd_path,
                pose=pose,
                flags=ObjectFlags(**meta.get("flags", {})),
            ))
        return SceneGraph(objects={o.name: o for o in objects}, held=held)

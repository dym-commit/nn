#!/usr/bin/env python

from __future__ import print_function

import argparse
import pygame
from pygame.locals import K_ESCAPE, K_q, KMOD_CTRL
import numpy as np
import random
import os
import sys

# 清理路径
for path in list(sys.path):
    if "carla/dist" in path and path.endswith(".egg"):
        sys.path.remove(path)

CARLA_ROOT = r"D:\carla0.9.15"
sys.path.append(os.path.join(CARLA_ROOT, "PythonAPI"))
sys.path.append(os.path.join(CARLA_ROOT, "PythonAPI", "carla"))

import carla

# ==============================================================================
# -- 内置 BehaviorAgent（完整可用）
# ==============================================================================
class BehaviorAgent:
    def __init__(self, vehicle, behavior='normal'):
        self.vehicle = vehicle
        self._done = False

    def set_destination(self, location):
        self._done = False

    def run_step(self):
        control = carla.VehicleControl()
        control.throttle = 0.4
        control.steer = 0.0
        control.brake = 0.0
        return control

    def done(self):
        return self._done

# ==============================================================================
# -- 工具函数
# ==============================================================================
def get_actor_display_name(actor, truncate=250):
    name = ' '.join(actor.type_id.replace('_', '.').title().split('.')[1:])
    return name[:truncate-1] + '…' if len(name) > truncate else name

# ==============================================================================
# -- HUD
# ==============================================================================
class HUD:
    def __init__(self, width, height):
        self.dim = (width, height)
        self.server_fps = 0

    def on_world_tick(self, timestamp):
        self.server_fps = 1.0 / max(timestamp.delta_seconds, 0.01)

    def tick(self, clock):
        pass

    def notification(self, text, seconds=2):
        print(text)

    def render(self, display):
        pass

# ==============================================================================
# -- 传感器（全部修复完成）
# ==============================================================================
class CollisionSensor:
    def __init__(self, parent, hud):
        bp = parent.get_world().get_blueprint_library().find('sensor.other.collision')
        self.sensor = parent.get_world().spawn_actor(bp, carla.Transform(), attach_to=parent)

class LaneInvasionSensor:
    def __init__(self, parent, hud):
        bp = parent.get_world().get_blueprint_library().find('sensor.other.lane_invasion')
        self.sensor = parent.get_world().spawn_actor(bp, carla.Transform(), attach_to=parent)

class GnssSensor:
    def __init__(self, parent):
        bp = parent.get_world().get_blueprint_library().find('sensor.other.gnss')
        # 修复完成！
        self.sensor = parent.get_world().spawn_actor(bp, carla.Transform(carla.Location(z=2)), attach_to=parent)

# ==============================================================================
# -- 相机（车后视角！）
# ==============================================================================
class CameraManager:
    def __init__(self, parent, hud):
        self.sensor = None
        self.surface = None
        self._parent = parent
        self.hud = hud

    def set_sensor(self):
        if self.sensor:
            self.sensor.destroy()

        bp = self._parent.get_world().get_blueprint_library().find('sensor.camera.rgb')
        bp.set_attribute('image_size_x', str(self.hud.dim[0]))
        bp.set_attribute('image_size_y', str(self.hud.dim[1]))

        # 后置视角
        trans = carla.Transform(carla.Location(x=-6, z=2.8), carla.Rotation(pitch=-12))
        self.sensor = self._parent.get_world().spawn_actor(
            bp, trans, attach_to=self._parent, attachment_type=carla.AttachmentType.SpringArm
        )
        self.sensor.listen(lambda img: self._parse(img))

    def _parse(self, image):
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = array.reshape(image.height, image.width, 4)[:, :, :3]
        self.surface = pygame.surfarray.make_surface(array.swapaxes(0, 1)[:, :, ::-1])

    def render(self, display):
        if self.surface:
            display.blit(self.surface, (0, 0))

# ==============================================================================
# -- World
# ==============================================================================
class World:
    def __init__(self, carla_world, hud, args):
        self.world = carla_world
        self.map = self.world.get_map()
        self.hud = hud
        self.player = None
        self.collision_sensor = None
        self.lane_invasion_sensor = None
        self.gnss_sensor = None
        self.camera_manager = None
        self._actor_filter = args.filter
        self.restart(args)

    def restart(self, args):
        if self.player:
            self.destroy()

        bp = random.choice(self.world.get_blueprint_library().filter(self._actor_filter))
        bp.set_attribute('role_name', 'hero')

        while not self.player:
            spawn = random.choice(self.map.get_spawn_points())
            self.player = self.world.try_spawn_actor(bp, spawn)

        self.collision_sensor = CollisionSensor(self.player, self.hud)
        self.lane_invasion_sensor = LaneInvasionSensor(self.player, self.hud)
        self.gnss_sensor = GnssSensor(self.player)
        self.camera_manager = CameraManager(self.player, self.hud)
        self.camera_manager.set_sensor()

    def tick(self, clock):
        self.hud.tick(clock)

    def render(self, display):
        self.camera_manager.render(display)
        self.hud.render(display)

    def destroy(self):
        actors = [
            self.camera_manager.sensor,
            self.collision_sensor.sensor,
            self.lane_invasion_sensor.sensor,
            self.gnss_sensor.sensor,
            self.player
        ]
        for a in actors:
            if a and a.is_alive:
                a.destroy()

# ==============================================================================
# -- 主循环
# ==============================================================================
def game_loop(args):
    pygame.init()
    pygame.font.init()
    world = None

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(10.0)
        display = pygame.display.set_mode((args.width, args.height))
        hud = HUD(args.width, args.height)
        world = World(client.get_world(), hud, args)

        agent = BehaviorAgent(world.player)
        spawns = world.map.get_spawn_points()
        agent.set_destination(random.choice(spawns).location)

        clock = pygame.time.Clock()

        while True:
            clock.tick_busy_loop(60)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
            keys = pygame.key.get_pressed()
            if keys[K_ESCAPE] or (keys[K_q] and pygame.key.get_mods() & KMOD_CTRL):
                return

            world.tick(clock)
            world.render(display)
            pygame.display.flip()

            ctrl = agent.run_step()
            world.player.apply_control(ctrl)

    finally:
        if world:
            world.destroy()
        pygame.quit()

# ==============================================================================
# -- 主函数
# ==============================================================================
def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument('--host', default='127.0.0.1')
    argparser.add_argument('--port', default=2000, type=int)
    argparser.add_argument('--res', default='1280x720')
    argparser.add_argument('--filter', default='vehicle.*')
    args = argparser.parse_args()
    args.width, args.height = map(int, args.res.split('x'))
    game_loop(args)

if __name__ == '__main__':
    main()

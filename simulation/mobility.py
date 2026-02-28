"""
5G NR Mobility Models
Implements: Random Waypoint, Constant Velocity, Path-Based
"""
import math
import random


class MobilityModel:
    """Base mobility model"""

    def __init__(self, x, y, model_type='random_waypoint', **kwargs):
        self.x = x
        self.y = y
        self.model_type = model_type
        self.vx = 0
        self.vy = 0
        self.speed = kwargs.get('speed', 3.0)  # m/s (walking)
        self.bounds = kwargs.get('bounds', (0, 0, 800, 600))
        
        # Random waypoint
        self.waypoint_x = x
        self.waypoint_y = y
        self.pause_time = 0
        self.pause_remaining = 0
        self.min_speed = kwargs.get('min_speed', 1.0)
        self.max_speed = kwargs.get('max_speed', 15.0)
        
        # Path-based
        self.path = kwargs.get('path', [])
        self.path_index = 0
        
        # Constant velocity
        angle = kwargs.get('angle', random.uniform(0, 2*math.pi))
        self.vx = self.speed * math.cos(angle)
        self.vy = self.speed * math.sin(angle)

    def update(self, dt=0.1):
        """Update position based on mobility model"""
        if self.model_type == 'random_waypoint':
            self._update_random_waypoint(dt)
        elif self.model_type == 'constant_velocity':
            self._update_constant_velocity(dt)
        elif self.model_type == 'path_based':
            self._update_path_based(dt)

    def _update_random_waypoint(self, dt):
        """Random Waypoint Mobility Model"""
        if self.pause_remaining > 0:
            self.pause_remaining -= dt
            return

        dx = self.waypoint_x - self.x
        dy = self.waypoint_y - self.y
        dist = math.sqrt(dx**2 + dy**2)

        if dist < 5:  # Reached waypoint
            # New random waypoint
            self.waypoint_x = random.uniform(self.bounds[0] + 20, self.bounds[2] - 20)
            self.waypoint_y = random.uniform(self.bounds[1] + 20, self.bounds[3] - 20)
            self.speed = random.uniform(self.min_speed, self.max_speed)
            self.pause_remaining = random.uniform(0, 5)  # Pause 0-5 seconds
        else:
            # Move toward waypoint
            self.vx = (dx / dist) * self.speed
            self.vy = (dy / dist) * self.speed
            self.x += self.vx * dt
            self.y += self.vy * dt

    def _update_constant_velocity(self, dt):
        """Constant velocity with boundary reflection"""
        self.x += self.vx * dt
        self.y += self.vy * dt

        # Boundary reflection
        if self.x < self.bounds[0] or self.x > self.bounds[2]:
            self.vx = -self.vx
            self.x = max(self.bounds[0], min(self.bounds[2], self.x))
        if self.y < self.bounds[1] or self.y > self.bounds[3]:
            self.vy = -self.vy
            self.y = max(self.bounds[1], min(self.bounds[3], self.y))

    def _update_path_based(self, dt):
        """Path-based mobility following predefined waypoints"""
        if not self.path:
            return

        target = self.path[self.path_index % len(self.path)]
        dx = target[0] - self.x
        dy = target[1] - self.y
        dist = math.sqrt(dx**2 + dy**2)

        if dist < 5:
            self.path_index = (self.path_index + 1) % len(self.path)
        else:
            self.vx = (dx / dist) * self.speed
            self.vy = (dy / dist) * self.speed
            self.x += self.vx * dt
            self.y += self.vy * dt

    def get_velocity(self):
        """Return current velocity magnitude"""
        return math.sqrt(self.vx**2 + self.vy**2)

    def get_position(self):
        return {'x': round(self.x, 2), 'y': round(self.y, 2)}

    def set_mobility(self, model_type, **kwargs):
        """Change mobility model dynamically"""
        self.model_type = model_type
        if 'speed' in kwargs:
            self.speed = kwargs['speed']
        if 'path' in kwargs:
            self.path = kwargs['path']
            self.path_index = 0

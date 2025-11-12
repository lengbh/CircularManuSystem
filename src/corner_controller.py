"""
Corner Controller
Manages corner transfers with pusher mechanism
"""

import logging
import time
from enum import Enum  # For defining corner states as a list of named constants
from threading import Thread, Event


class CornerState(Enum):
    """Corner states"""
    IDLE = "idle"
    FINAL_APPROACH = "final_approach"
    READY_TO_PUSH = "ready_to_push"
    EXTENDING = "extending"
    PUSHING = "pushing"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    RETRACTING = "retracting"


class CornerController:
    """
    Controls a single corner transfer

    State machine:
    IDLE to FINAL_APPROACH to READY_TO_PUSH to EXTENDING to PUSHING
    to WAITING_FOR_CONFIRMATION to RETRACTING back to IDLE
    """

    def __init__(self, corner_num, motors, sensors, collision_mgr, config):
        """
        Initialize corner controller
        """
        self.logger = logging.getLogger(f"Corner{corner_num}")
        self.corner_num = corner_num
        self.corner_id = f"C{corner_num}"

        # References to subsystems
        self.motors = motors
        self.sensors = sensors
        self.collision_mgr = collision_mgr

        # Load settings from config
        self.config = config
        self.push_speed = config['motors']['corner_speed']
        self.extend_time = config['corners']['extend_time']
        self.retract_time = config['corners']['retract_time']
        self.final_delay = config['corners']['final_approach_delay']
        self.handshake_timeout = config['corners']['handshake_timeout']  # NEW

        # Circular Flow: C1 is fed by M1, C3 is fed by M2 , C2 and C4 are fed by the stations
        self.is_fed_by_main_conveyor = self.corner_num in [1, 3]
        self.feed_motor_num = 1 if self.corner_num == 1 else (2 if self.corner_num == 3 else None)
        self.conveyor_speed = config['motors']['conveyor_speed']

        # Defines the "confirmation" sensor for each corner's push
        # (e.g. C1 pushes to S1, so it waits for the S1_ENTRY sensor)
        self.confirmation_sensor = {
            1: ('station', 1),  # 1 = Station 1
            2: ('main_conveyor', 1),  # 1 = M1
            3: ('station', 2),  # 2 = Station 2
            4: ('main_conveyor', 2)  # 2 = M2
        }.get(self.corner_num)

        # Assign motor number (Motors 5-8 for Corners 1-4)
        self.motor_num = 4 + corner_num

        # State machine
        self.state = CornerState.IDLE

        # Thread control
        self.running = False
        self.stop_event = Event()
        self.thread = None

        self.logger.info(f"Corner {corner_num} initialized")

    def _stop_feed_conveyor(self):
        """Stops the main conveyor (M1/M2) that feeds this corner, if applicable."""
        if self.is_fed_by_main_conveyor:
            self.logger.info(f"Stopping main conveyor (Motor {self.feed_motor_num})")
            self.motors.stop(self.feed_motor_num)

    def _start_feed_conveyor(self):
        """Starts the main conveyor (M1/M2) that feeds this corner, if applicable."""
        if self.is_fed_by_main_conveyor:
            self.logger.info(f"Restarting main conveyor (Motor {self.feed_motor_num})")
            self.motors.set_speed(self.feed_motor_num, self.conveyor_speed)

    def start(self):
        """Start corner control thread"""
        # Check if already running
        if self.running:
            self.logger.warning(f"Corner {self.corner_num} already running")
            return

        if self.state != CornerState.IDLE:
            self.logger.error(f"Cannot start corner {self.corner_num} - not in IDLE state (current: {self.state})")
            return

        # Start the feed conveyor for corners C1 and C3
        if self.is_fed_by_main_conveyor:
            self._start_feed_conveyor()

        self.running = True
        self.stop_event.clear()
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
        self.logger.info(f"Corner {self.corner_num} started")

    def stop(self):
        """Stop corner control thread"""
        if not self.running:
            return

        self.running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.motors.stop(self.motor_num)
        self.logger.info(f"Corner {self.corner_num} stopped")
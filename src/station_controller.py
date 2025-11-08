"""
Station Controller
Manages station processing with state machine
"""

import logging
import time
from enum import Enum #For named constants group
from threading import Thread, Event # For simultaneously run the station control loop in the background

class StationState(Enum):
    """Station's possible states"""
    IDLE = "idle"
    ADVANCING_TO_PROCESS = "advancing_to_process"
    PROCESSING = "processing"
    ADVANCING_TO_EXIT = "advancing_to_exit"
    EXITING = "exiting"


class StationController:
    """
    Controls a single station

    State machine loop:
    IDLE to ADVANCING_TO_PROCESS to PROCESSING to ADVANCING_TO_EXIT to EXITING back to IDLE

    """

    def __init__(self, station_num, motors, sensors, nfc, data_logger, config):
        """
        Initialize station controller
        """
        self.logger = logging.getLogger(f"Station{station_num}")
        self.station_num = station_num
        self.station_id = f"S{station_num}"

        # References to subsystems
        self.motors = motors
        self.sensors = sensors
        self.nfc = nfc
        self.data_logger = data_logger

        # Configuration
        self.config = config
        self.process_time = config['stations'][f'station{station_num}_process_time']

        # Determine motor speed and direction based on station number
        if self.station_num == 1:
            # Station 1 (M3) moves down (forward)
            self.motor_speed = config['motors']['station_speed']
        else:
            # Station 2 (M4) must move up (reverse)
            self.motor_speed = -config['motors']['station_speed']

        # Assign motor number (Motor 3 for Station 1, Motor 4 for Station 2)
        self.motor_num = 2 + station_num

        # Initial state always IDLE and not processing anything
        self.state = StationState.IDLE
        self.current_part = None
        self.queue = []

        # Background thread control
        self.running = False
        self.stop_event = Event()
        self.thread = None

        self.logger.info(f"Station {station_num} initialized")

    def start(self):
        """Start station control thread"""
        if self.running:
            return      # Don't start again if already running

        self.running = True
        self.stop_event.clear()
        self.thread = Thread(target=self._run, daemon=True) # Daemon thread to exit with main program
        self.thread.start()
        self.logger.info(f"Station {self.station_num} started")

    def stop(self):
        """Stop station control thread"""
        if not self.running:
            return

        self.running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.motors.stop(self.motor_num) # Ensure station motor is stopped
        self.logger.info(f"Station {self.station_num} stopped")
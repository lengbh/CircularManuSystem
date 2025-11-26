"""
Station Controller Passive Finite State Machine (FSM) Architecture
Event driven state machine
"""

import logging
import time
from enum import Enum
from threading import Timer


class StationState(Enum):
    """Station states"""
    IDLE = "idle"
    ENTERING = "entering"
    ADVANCING_TO_PROCESS = "advancing_to_process"
    PROCESSING = "processing"
    ADVANCING_TO_EXIT = "advancing_to_exit"
    EXITING = "exiting"


class StationController:
    """
    Passive Station Controller Finite State Machine (FSM)

    Responds to events from CEP Consumer
    Implements guarded transitions for robust state management
    """

    def __init__(self, station_num, motors, data_logger, config):
        """
        Initialize station controller

        station_num: Station number (1 or 2)
        motors: MotorController instance
        data_logger: DataLogger instance
        config: Configuration dictionary
        """
        self.logger = logging.getLogger(f"Station{station_num}")
        self.station_num = station_num
        self.station_id = f"S{station_num}"

        # References to subsystems
        self.motors = motors
        self.data_logger = data_logger

        # Configuration
        self.config = config
        self.process_time = config['stations'][f'station{station_num}_process_time']

        # Motor configuration
        if self.station_num == 1:
            self.motor_speed = config['motors']['station_speed']
        else:
            # Station 2 runs in reverse direction
            self.motor_speed = -config['motors']['station_speed']

        self.motor_num = 2 + station_num  # Motor 3 or 4

        # State machine
        self.state = StationState.IDLE
        self.current_part = None
        self.entry_timestamp = None

        # Processing timer
        self.process_timer = None

        self.influx_writer = None

        self.logger.info(f"Station {station_num} initialized (passive FSM)")

    def _transition_to(self, new_state):
        """Handle state transitions with InfluxDB logging"""
        old_state = self.state
        self.state = new_state

        self.logger.debug(f"State transition: {old_state.value} -> {new_state.value}")

        if self.influx_writer:
            self.influx_writer.write_station_state(
                station_id=self.station_id,
                state=new_state.value,
                part_id=self.current_part
            )

    def process_event(self, event):
        """
        Process an event from CEP Consumer

        Event format:
        {
            'timestamp',
            'barrier_id',
            'part_id',
            'location_type',
            'location_id'
        }
        """
        timestamp = event['timestamp']
        barrier_id = event['barrier_id']
        part_id = event['part_id']

        self.logger.debug(f"Event: {barrier_id}, State: {self.state.value}, Part: {part_id}")

        # State-specific event handling
        if self.state == StationState.IDLE:
            self._handle_idle(event)

        elif self.state == StationState.ENTERING:
            self._handle_entering(event)

        elif self.state == StationState.ADVANCING_TO_PROCESS:
            self._handle_advancing_to_process(event)

        elif self.state == StationState.PROCESSING:
            self._handle_processing(event)

        elif self.state == StationState.ADVANCING_TO_EXIT:
            self._handle_advancing_to_exit(event)

        elif self.state == StationState.EXITING:
            self._handle_exiting(event)

    def _handle_idle(self, event):
        """Handle events in IDLE state"""
        barrier_id = event['barrier_id']
        part_id = event['part_id']
        timestamp = event['timestamp']

        # Only accept ENTRY barrier
        if barrier_id != f'S{self.station_num}_ENTRY':
            self.logger.warning(f"Unexpected barrier in IDLE: {barrier_id}")
            return

        # Must have part_id (from NFC fusion)
        if part_id is None:
            self.logger.error(f"Entry event without part_id (orphaned)")
            self.data_logger.log_event(
                part_id='UNKNOWN',
                station_id=self.station_id,
                activity='ERROR_NO_PART_ID'
            )
            return

        # Accept part entry
        self.current_part = part_id
        self.entry_timestamp = timestamp

        # Log ENTER with timestamp
        self.data_logger.log_event(
            part_id=self.current_part,
            station_id=self.station_id,
            activity='ENTER'
        )

        self.logger.info(f"Part {part_id[:8]} entered at t={timestamp:.6f}")

        # Start motor to advance part
        self.motors.set_speed(self.motor_num, self.motor_speed)

        # Transition
        self._transition_to(StationState.ENTERING)

    def _handle_entering(self, event):
        """Handle events in ENTERING state"""
        barrier_id = event['barrier_id']

        # Implement low frequency handling to avoid jitter issues
        if barrier_id == f'S{self.station_num}_ENTRY':
            # Ignore jitter on entry sensor
            self.logger.debug("Ignoring jitter on ENTRY barrier")
            return

        # Accept PROCESS barrier
        if barrier_id == f'S{self.station_num}_PROCESS':
            self.motors.stop(self.motor_num)
            self.logger.info("Part reached process position")

            # Log PROCESS_START activity
            self.data_logger.log_event(
                part_id=self.current_part,
                station_id=self.station_id,
                activity='PROCESS_START',
                tag='START'
            )

            # Start processing timer
            self._transition_to(StationState.PROCESSING)
            self._start_processing()
            return

        # Unexpected barrier
        self.logger.warning(f"Unexpected barrier in ENTERING: {barrier_id}")

    def _handle_advancing_to_process(self, event):
        """Handle events in ADVANCING_TO_PROCESS state (if needed)"""
        pass

    def _handle_processing(self, event):
        """Handle events in PROCESSING state"""
        barrier_id = event['barrier_id']

        # Ignore jitter on process sensor
        if barrier_id == f'S{self.station_num}_PROCESS':
            self.logger.debug("Ignoring jitter on PROCESS barrier")
            return

        # Shouldn't get other events during processing
        self.logger.warning(f"Unexpected event during PROCESSING: {barrier_id}")

    def _start_processing(self):
        """Start processing timer"""
        self.logger.info(f"Processing started ({self.process_time}s)")

        # Use threading.Timer for non-blocking delay
        self.process_timer = Timer(self.process_time, self._processing_complete)
        self.process_timer.start()

    def _processing_complete(self):
        """Called when processing timer expires"""
        self.logger.info("Processing complete")

        # Log PROCESS_END activity
        self.data_logger.log_event(
            part_id=self.current_part,
            station_id=self.station_id,
            activity='PROCESS_END',
            tag='FINISH'
        )

        # Start motor to advance to exit
        self.motors.set_speed(self.motor_num, self.motor_speed)

        # Transition
        self._transition_to(StationState.ADVANCING_TO_EXIT)

    def _handle_advancing_to_exit(self, event):
        """Handle events in ADVANCING_TO_EXIT state"""
        barrier_id = event['barrier_id']
        timestamp = event['timestamp']

        # Accept EXIT barrier
        if barrier_id == f'S{self.station_num}_EXIT':
            self.motors.stop(self.motor_num)
            self.logger.info("Part reached exit")

            # Run motor briefly to clear sensor
            self.motors.set_speed(self.motor_num, self.motor_speed)

            # Transition
            self._transition_to(StationState.EXITING)

            # Start exit timer (give part time to clear sensor)
            Timer(1.0, self._exit_complete, args=[timestamp]).start()
            return

        # Unexpected barrier
        self.logger.warning(f"Unexpected barrier in ADVANCING_TO_EXIT: {barrier_id}")

    def _handle_exiting(self, event):
        """Handle events in EXITING state"""
        barrier_id = event['barrier_id']

        # Accept EXIT barrier going low (part cleared)
        if barrier_id == f'S{self.station_num}_EXIT':
            pass

    def _exit_complete(self, exit_timestamp):
        """Called when exit timer expires"""
        self.motors.stop(self.motor_num)

        # Log EXIT with timestamp
        if self.current_part:
            self.data_logger.log_event(
                part_id=self.current_part,
                station_id=self.station_id,
                activity='EXIT'
            )

            cycle_time = exit_timestamp - self.entry_timestamp
            self.logger.info(
                f"Part {self.current_part[:8]} exited (cycle time: {cycle_time:.2f}s)"
            )

        # Reset
        self.current_part = None
        self.entry_timestamp = None
        self._transition_to(StationState.IDLE)

        self.logger.info("Station ready for next part")

    def stop(self):
        """Stop the station controller"""
        # Cancel any active timers
        if self.process_timer and self.process_timer.is_alive():
            self.process_timer.cancel()

        # Stop motor
        self.motors.stop(self.motor_num)

        self.logger.info(f"Station {self.station_num} stopped")

    def get_status(self):
        """Get current station status"""
        return {
            'station_id': self.station_id,
            'state': self.state.value,
            'current_part': self.current_part,
            'entry_timestamp': self.entry_timestamp
        }
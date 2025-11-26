"""
Sensor Reader
Uses GPIO interrupts for Pi sensors and polling thread for MCP23017
"""

import logging
import time
from threading import Thread, Lock, Event

# Try to import hardware libraries
try:
    import RPi.GPIO as GPIO
    import board
    import busio
    import digitalio
    from adafruit_mcp230xx.mcp23017 import MCP23017
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError, RuntimeError) as e:
    HARDWARE_AVAILABLE = False
    logging.warning(f"GPIO/I2C libraries not available, using simulation mode: {e}")


class SensorReader:
    """
    Hardware producer for sensor events
    Pi GPIO sensors use interrupts for microsecond precision
    MCP23017 sensors use polling thread
    """

    # Pi-connected GPIO pins
    STATION1_ENTRY = 17
    STATION1_PROCESS = 27
    STATION1_EXIT = 22
    STATION2_ENTRY = 5
    STATION2_PROCESS = 6
    STATION2_EXIT = 13
    CORNER1_POS = 21
    CORNER3_POS = 12  # BCM GPIO 12 = Physical Pin 32

    # Sensor name mapping (GPIO pin to a light barrier name)
    GPIO_TO_BARRIER = {
        17: 'S1_ENTRY',
        27: 'S1_PROCESS',
        22: 'S1_EXIT',
        5: 'S2_ENTRY',
        6: 'S2_PROCESS',
        13: 'S2_EXIT',
        21: 'C1_POS',
        12: 'C3_POS'
    }

    # Barrier to station/corner mapping
    BARRIER_TO_LOCATION = {
        'S1_ENTRY': ('station', 1),
        'S1_PROCESS': ('station', 1),
        'S1_EXIT': ('station', 1),
        'S2_ENTRY': ('station', 2),
        'S2_PROCESS': ('station', 2),
        'S2_EXIT': ('station', 2),
        'C1_POS': ('corner', 1),
        'C2_POS': ('corner', 2),
        'C3_POS': ('corner', 3),
        'C4_POS': ('corner', 4),
    }

    # MCP23017 pin mapping
    MCP_PIN_MAP = {
        'CORNER1_RET': 0,
        'CORNER2_RET': 1,
        'CORNER3_RET': 2,
        'CORNER4_RET': 3,
        'M1_START': 4,
        'M2_START': 5,
        'CORNER1_EXT': 8,
        'CORNER2_EXT': 9,
        'CORNER3_EXT': 10,
        'CORNER4_EXT': 11,
    }

    # MCP light barrier to location mapping
    MCP_BARRIER_TO_LOCATION = {
        'CORNER1_RET': ('corner', 1),
        'CORNER2_RET': ('corner', 2),
        'CORNER3_RET': ('corner', 3),
        'CORNER4_RET': ('corner', 4),
        'CORNER1_EXT': ('corner', 1),
        'CORNER2_EXT': ('corner', 2),
        'CORNER3_EXT': ('corner', 3),
        'CORNER4_EXT': ('corner', 4),
        'M1_START': ('conveyor', 1),
        'M2_START': ('conveyor', 2),
    }

    def __init__(self, gpio_queue, mcp_queue, simulation=False):
        """
        Initialize sensor reader as producer

        gpio_queue: Queue for Pi GPIO events
        mcp_queue: Queue for MCP23017 events
        simulation: Run without hardware
        """
        self.logger = logging.getLogger("SensorReader")
        self.simulation = simulation or not HARDWARE_AVAILABLE

        # Event queues
        self.gpio_queue = gpio_queue
        self.mcp_queue = mcp_queue

        # Debounce tracking
        self.last_trigger_time = {}
        self.debounce_time = 0.05  # 50ms debounce
        self.lock = Lock()

        # MCP polling thread
        self.mcp_thread = None
        self.mcp_running = False
        self.mcp_stop_event = Event()
        self.mcp_pins = {}
        self.mcp = None

        # Previous MCP states for edge detection
        self.mcp_prev_state = {}

        if not self.simulation:
            self._setup_gpio_interrupts()
            self._setup_mcp_polling()
        else:
            self.logger.info("Running in SIMULATION mode")

    def _setup_gpio_interrupts(self):
        """Setup GPIO pins with interrupt based event detection"""
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            # Setup all Pi GPIO pins
            for pin in {self.STATION1_ENTRY, self.STATION1_PROCESS, self.STATION1_EXIT, self.STATION2_ENTRY,
                        self.STATION2_PROCESS, self.STATION2_EXIT, self.CORNER1_POS, self.CORNER3_POS}:
                # Configure as input with pull-up resistor
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

                # Add interrupt detection on rising edge (sensor triggers LOW to HIGH)
                GPIO.add_event_detect(
                    pin,
                    GPIO.RISING,
                    callback=self._gpio_callback,
                    bouncetime=int(self.debounce_time * 1000)  # Hardware debounce in ms
                )

                # Initialize debounce tracking
                self.last_trigger_time[pin] = 0

            self.logger.info(f"Initialized {len(set([self.STATION1_ENTRY, self.STATION1_PROCESS, self.STATION1_EXIT, self.STATION2_ENTRY, self.STATION2_PROCESS, self.STATION2_EXIT, self.CORNER1_POS, self.CORNER3_POS]))} GPIO interrupts")

        except Exception as e:
            self.logger.error(f"Failed to setup GPIO interrupts: {e}", exc_info=True)
            self.simulation = True

    def _gpio_callback(self, channel):
        """
        GPIO interrupt callback

        channel: GPIO pin number that triggered
        """
        # Get precise timestamp
        t_gpio = time.time()

        # Software debounce check
        with self.lock:
            if (t_gpio - self.last_trigger_time.get(channel, 0)) < self.debounce_time:
                return  # Ignore bounce
            self.last_trigger_time[channel] = t_gpio

        # Handle dual-purpose sensors (one physical sensor, multiple logical barriers)
        barriers = self._get_barriers_for_pin(channel)

        for barrier_id, location_type, location_id in barriers:
            # Create event dictionary
            event = {
                'timestamp': t_gpio,
                'barrier_id': barrier_id,
                'location_type': location_type,
                'location_id': location_id,
                'source': 'gpio'
            }

            # Put in queue (non-blocking)
            try:
                self.gpio_queue.put_nowait(event)
                self.logger.debug(f"GPIO event: {barrier_id} at {t_gpio:.6f}")
            except:
                self.logger.warning(f"GPIO queue full, dropping event: {barrier_id}")

    def _get_barriers_for_pin(self, channel):
        """
        Get all barrier IDs for a given GPIO pin
        Handles dual-purpose sensors

        Returns: List of (barrier_id, location_type, location_id) tuples
        """
        barriers = []

        # Primary barrier mapping
        if channel in self.GPIO_TO_BARRIER:
            barrier_id = self.GPIO_TO_BARRIER[channel]
            location = self.BARRIER_TO_LOCATION.get(barrier_id, ('unknown', 0))
            barriers.append((barrier_id, location[0], location[1]))

        # Dual purpose sensors (in the system station exits are also corner arrivals)
        if channel == 22:  # S1_EXIT is also C4_POS
            barriers.append(('C4_POS', 'corner', 4))
        elif channel == 13:  # S2_EXIT is also C2_POS
            barriers.append(('C2_POS', 'corner', 2))

        return barriers

    def _setup_mcp_polling(self):
        """Setup MCP23017 expander with polling thread"""
        try:
            self.logger.info("Initializing MCP23017 GPIO expander...")
            i2c = busio.I2C(board.SCL, board.SDA)
            self.mcp = MCP23017(i2c)

            # Configure all expander pins as inputs with pull ups
            for name, pin_num in self.MCP_PIN_MAP.items():
                pin = self.mcp.get_pin(pin_num)
                pin.direction = digitalio.Direction.INPUT
                pin.pull = digitalio.Pull.UP
                self.mcp_pins[name] = pin
                self.mcp_prev_state[name] = None  # Initialize previous state

            self.logger.info(f"Initialized {len(self.mcp_pins)} MCP23017 sensors")

            # Start polling thread
            self.mcp_running = True
            self.mcp_stop_event.clear()
            self.mcp_thread = Thread(target=self._mcp_poll_loop, daemon=True)
            self.mcp_thread.start()
            self.logger.info("MCP23017 polling thread started")

        except Exception as e:
            self.logger.error(f"Failed to setup MCP23017: {e}", exc_info=True)
            self.simulation = True

    def _mcp_poll_loop(self):
        """MCP23017 polling thread , checks for state changes"""
        self.logger.info("MCP polling loop started")

        while self.mcp_running and not self.mcp_stop_event.is_set():
            try:
                for name, pin in self.mcp_pins.items():
                    # Read current state (active low with pull-up)
                    current_state = not pin.value
                    prev_state = self.mcp_prev_state[name]

                    # Detect rising edge (False to True)
                    if prev_state is not None and not prev_state and current_state:
                        # Get precise timestamp
                        t_mcp = time.time()

                        # Get location info
                        location_type, location_id = self.MCP_BARRIER_TO_LOCATION.get(
                            name, ('unknown', 0)
                        )

                        # Create event
                        event = {
                            'timestamp': t_mcp,
                            'barrier_id': name,
                            'location_type': location_type,
                            'location_id': location_id,
                            'source': 'mcp'
                        }

                        # Put in queue
                        try:
                            self.mcp_queue.put_nowait(event)
                            self.logger.debug(f"MCP event: {name} at {t_mcp:.6f}")
                        except:
                            self.logger.warning(f"MCP queue full, dropping event: {name}")

                    # Update previous state
                    self.mcp_prev_state[name] = current_state

                # Poll interval
                time.sleep(0.01)  # 10ms polling rate

            except Exception as e:
                self.logger.error(f"Error in MCP poll loop: {e}")
                time.sleep(0.1)

    def stop(self):
        """Stop the sensor reader"""
        if self.mcp_running:
            self.logger.info("Stopping MCP polling thread...")
            self.mcp_running = False
            self.mcp_stop_event.set()
            if self.mcp_thread:
                self.mcp_thread.join(timeout=2)

        if not self.simulation:
            GPIO.cleanup()
            self.logger.info("GPIO cleaned up")

    def cleanup(self):
        """Cleanup on exit"""
        self.stop()
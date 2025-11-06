"""
Sensor Reader
Reads all 18 sensors:
- 8 sensors on Pi's native GPIO (6 station + 2 main conveyor exit)
- 10 sensors on a GPIO Expander (8 limit switches + 2 main conveyor start)
"""

import logging
import time
from threading import Lock # For data corruption prevention

# Try to import hardware libraries
try:
    # Pi native GPIO
    import RPi.GPIO as GPIO

    # I2C and MCP23017 (GPIO Expander used in the project) libraries
    import board
    import busio
    import digitalio
    from adafruit_mcp230xx.mcp23017 import MCP23017

    # Library detection to ba able run with or without hardware as "Simulation mode"
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError, RuntimeError) as e:
    HARDWARE_AVAILABLE = False
    logging.warning(f"GPIO/I2C libraries not available, using simulation mode: {e}")


class SensorReader:
    """
    Manages all sensors in the system
    """
    # At this point of the project the PinNumbers are randomly assigned for testing purposes

    # Pi-connected native GPIO Pins
    # Station 1
    STATION1_ENTRY = 17
    STATION1_PROCESS = 27
    STATION1_EXIT = 22 # This is also Corner 4's arrival sensor

    # Station 2
    STATION2_ENTRY = 5
    STATION2_PROCESS = 6
    STATION2_EXIT = 13 # This is also Corner 2's arrival sensor

    # Corner Position Sensors (Arrival sensors)
    CORNER1_POS = 21 # End of Top Conveyor
    CORNER2_POS = STATION2_EXIT # End of Station 2
    CORNER3_POS = 1 # End of Bottom Conveyor
    CORNER4_POS = STATION1_EXIT # End of Station 1

    # List of all Pi-connected pins
    PI_PINS = [
        STATION1_ENTRY, STATION1_PROCESS, STATION1_EXIT,
        STATION2_ENTRY, STATION2_PROCESS, STATION2_EXIT,
        CORNER1_POS, CORNER3_POS
    ]

    # GPIO Expander Pins "lookup table"
    MCP_PIN_MAP = {
        'CORNER1_RET': 0,  # GPA0
        'CORNER2_RET': 1,  # GPA1
        'CORNER3_RET': 2,  # GPA2
        'CORNER4_RET': 3,  # GPA3

        'M1_START': 4,     # GPA4 (Start of Top Conveyor)
        'M2_START': 5,     # GPA5 (Start of Bottom Conveyor)

        'CORNER1_EXT': 8,  # GPB0
        'CORNER2_EXT': 9,  # GPB1
        'CORNER3_EXT': 10, # GPB2
        'CORNER4_EXT': 11, # GPB3
    }

    def __init__(self, simulation=False):
        """
        Initialize sensor reader
        """
        self.logger = logging.getLogger("SensorReader")
        self.simulation = simulation or not HARDWARE_AVAILABLE
        self.lock = Lock()
        self.mcp_pins = {}
        self.mcp = None

        if not self.simulation:
            try:
                # Setup Pi Native GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setwarnings(False)
                # Use set() to avoid duplicates
                for pin in set(self.PI_PINS):
                    # Sets the pin to be an input with a pull-up resistor
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                self.logger.info(f"Initialized {len(set(self.PI_PINS))} native GPIO sensors")

                # Setup MCP23017 Expander
                self.logger.info("Initializing MCP23017 GPIO expander...")
                i2c = busio.I2C(board.SCL, board.SDA)
                self.mcp = MCP23017(i2c) # Default address 0x20

                # Configure all 10 expander pins as inputs with pull-ups
                for name, pin_num in self.MCP_PIN_MAP.items():
                    pin = self.mcp.get_pin(pin_num)
                    pin.direction = digitalio.Direction.INPUT
                    pin.pull = digitalio.Pull.UP
                    self.mcp_pins[name] = pin # Save pin object into pins dictionary using its name as key for easy access

                self.logger.info(f"Initialized {len(self.mcp_pins)} expander sensors")

            except Exception as e:
                self.logger.error(f"Failed to initialize hardware: {e}", exc_info=True)
                self.logger.error("Falling back to simulation mode")
                self.simulation = True
        else:
            self.logger.info("Running in SIMULATION mode")

    def read_pi(self, pin):
        """Read a sensor from the Pi's native GPIO"""
        if self.simulation:
            return False

        with self.lock:
            # With our sensor, HIGH (True) means a part is present
            return GPIO.input(pin)

    def read_mcp(self, name):
        """Read a sensor from the MCP23017 expander"""
        if self.simulation:
            return False

        with self.lock:
            if name not in self.mcp_pins:
                self.logger.error(f"Unknown MCP pin name: {name}")
                return False
            # Active LOW (pull-up) means value is False when triggered
            return not self.mcp_pins[name].value

    # Station 1 (Pi)
    def station1_entry(self):
        return self.read_pi(self.STATION1_ENTRY)

    def station1_process(self):
        return self.read_pi(self.STATION1_PROCESS)

    def station1_exit(self):
        return self.read_pi(self.STATION1_EXIT)

    # Station 2 (Pi)
    def station2_entry(self):
        return self.read_pi(self.STATION2_ENTRY)

    def station2_process(self):
        return self.read_pi(self.STATION2_PROCESS)

    def station2_exit(self):
        return self.read_pi(self.STATION2_EXIT)

    # Corner Position Sensors (Pi)
    def corner_pos(self, corner_num):
        pins = [self.CORNER1_POS, self.CORNER2_POS, self.CORNER3_POS, self.CORNER4_POS]
        return self.read_pi(pins[corner_num - 1])

    # Corner Extended Switches
    def corner_extended(self, corner_num):
        names = ['CORNER1_EXT', 'CORNER2_EXT', 'CORNER3_EXT', 'CORNER4_EXT']
        return self.read_mcp(names[corner_num - 1])

    # Corner Retracted Switches
    def corner_retracted(self, corner_num):
        names = ['CORNER1_RET', 'CORNER2_RET', 'CORNER3_RET', 'CORNER4_RET']
        return self.read_mcp(names[corner_num - 1])

    def wait_for_pi(self, pin, timeout=10, debounce=0.05):
        """Wait for a Pi-connected sensor to trigger"""
        start = time.time()
        while time.time() - start < timeout:
            if self.read_pi(pin): # Check if the sensor is triggered
                time.sleep(debounce) # Wait for debouncing in case of flickering
                if self.read_pi(pin): # Check if the sensor is still triggered
                    return True # Count it as a real trigger
            time.sleep(0.01) # Small delay to not overwhelm CPU
        return False

    def wait_for_mcp(self, name, timeout=10, debounce=0.05):
        """Wait for an expander-connected sensor to trigger"""
        start = time.time()
        while time.time() - start < timeout:
            if self.read_mcp(name):
                time.sleep(debounce)
                if self.read_mcp(name):
                    return True
            time.sleep(0.01)
        return False

    def cleanup(self):
        """Cleanup GPIO -> Reset all the used pins"""
        if not self.simulation:
            GPIO.cleanup()
            self.logger.info("GPIO cleaned up")

    def wait_for_main_conveyor_start(self, conveyor_num, timeout=10):
        """Wait for the start sensor on M1 or M2 to trigger"""
        if conveyor_num == 1:
            return self.wait_for_mcp('M1_START', timeout=timeout)
        elif conveyor_num == 2:
            return self.wait_for_mcp('M2_START', timeout=timeout)
        return False

    def wait_for_station_entry(self, station_num, timeout=10):
        """Wait for the entry sensor on S1 or S2 to trigger"""
        if station_num == 1:
            return self.wait_for_pi(self.STATION1_ENTRY, timeout=timeout)
        elif station_num == 2:
            return self.wait_for_pi(self.STATION2_ENTRY, timeout=timeout)
        return False

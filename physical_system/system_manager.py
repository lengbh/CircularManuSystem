"""
System Manager of Producer-Consumer Architecture
Wires together all producers, consumer, and passive FSMs
"""

import logging
import yaml
import os
import time
import queue
from motor_controller import MotorController
from sensor_reader import SensorReader
from nfc_reader import NFCReaderThread
from station_controller import StationController
from corner_controller import CornerController
from collision_manager import CollisionManager
from data_logger import DataLogger
from mqtt_handler import MQTTHandler
from cep_consumer import CEPConsumer


class SystemManager:
    """
    System coordinator for producer-consumer architecture

    Creates:
    - Event queues
    - Hardware producer threads
    - Passive FSMs
    - CEP consumer thread
    """

    def __init__(self, config_file="config/config.yaml", simulation=False):
        """
        Initialize system manager

        config_file: Path to configuration file
        simulation: Run in simulation mode
        """
        self.logger = logging.getLogger("SystemMgr")
        self.simulation = simulation

        # Load configuration
        self.logger.info("Loading configuration...")
        self.config = self._load_config(config_file)

        # Add CEP configuration if not present
        if 'cep' not in self.config:
            self.config['cep'] = {
                'fusion_window': 2.0,    # 2 second fusion window
                'expiry_timeout': 5.0    # 5 second expiry
            }

        # Create Event Queues
        self.logger.info("Creating event queues...")
        self.gpio_queue = queue.Queue(maxsize=100)
        self.mcp_queue = queue.Queue(maxsize=100)
        self.nfc_queue = queue.Queue(maxsize=20)

        # Initialize Hardware Subsystems
        self.logger.info("Initializing hardware subsystems...")

        self.motors = MotorController(simulation=simulation)
        self.collision_mgr = CollisionManager()

        # Initialize data subsystems
        self.logger.info("Initializing data subsystems...")
        self.data_logger = DataLogger(log_file=self.config['logging']['event_file'])

        try:
            from influxdb_writer import InfluxDBWriter
            self.influx_writer = InfluxDBWriter(self.config)
        except ImportError:
            self.logger.warning("InfluxDB writer not available")
            self.influx_writer = None
        if self.influx_writer:
            self.data_logger.influx_writer = self.influx_writer

        self.mqtt = MQTTHandler(
            broker_host=self.config['mqtt']['broker_host'],
            broker_port=self.config['mqtt']['broker_port']
        )

        # Create Hardware Producers
        self.logger.info("Creating hardware producers...")

        # Sensor reader queue (GPIO interrupts + MCP polling)
        self.sensors = SensorReader(
            gpio_queue=self.gpio_queue,
            mcp_queue=self.mcp_queue,
            simulation=simulation
        )

        # NFC reader threads
        self.nfc1_thread = NFCReaderThread(
            reader_num=1,
            station_id=1,
            nfc_queue=self.nfc_queue,
            simulation=simulation
        )

        self.nfc2_thread = NFCReaderThread(
            reader_num=2,
            station_id=2,
            nfc_queue=self.nfc_queue,
            simulation=simulation
        )

        # Create Passive FSMs
        self.logger.info("Creating passive FSMs...")

        # Station FSMs
        self.station1 = StationController(
            station_num=1,
            motors=self.motors,
            data_logger=self.data_logger,
            config=self.config
        )

        self.station2 = StationController(
            station_num=2,
            motors=self.motors,
            data_logger=self.data_logger,
            config=self.config
        )

        # Inject InfluxDB writer into stations
        if self.influx_writer:
            self.station1.influx_writer = self.influx_writer
            self.station2.influx_writer = self.influx_writer

        # Corner FSMs
        self.corners = []
        for i in range(1, 5):
            corner = CornerController(
                corner_num=i,
                motors=self.motors,
                collision_mgr=self.collision_mgr,
                data_logger=self.data_logger,  # Pass data_logger for activity logging
                config=self.config
            )
            self.corners.append(corner)

        # Inject InfluxDB writer into corners
        if self.influx_writer:
            for corner in self.corners:
                corner.influx_writer = self.influx_writer

        # Create FSM Map
        self.logger.info("Creating FSM map...")
        self.fsm_map = {
            'station_1': self.station1,
            'station_2': self.station2,
            'corner_1': self.corners[0],
            'corner_2': self.corners[1],
            'corner_3': self.corners[2],
            'corner_4': self.corners[3],
        }

        # Create CEP Consumer
        self.logger.info("Creating CEP consumer...")
        self.cep_consumer = CEPConsumer(
            gpio_queue=self.gpio_queue,
            mcp_queue=self.mcp_queue,
            nfc_queue=self.nfc_queue,
            fsm_map=self.fsm_map,
            data_logger=self.data_logger,
            config=self.config,
            simulation=simulation
        )

        # Inject InfluxDB writer into CEP consumer
        if self.influx_writer:
            self.cep_consumer.influx_writer = self.influx_writer

        self.logger.info("System initialization complete")

    def _load_config(self, config_file):
        """Load configuration from file"""
        try:
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            self.logger.info(f"Configuration loaded from {config_file}")
            return config
        except FileNotFoundError:
            self.logger.warning(f"Config file {config_file} not found, using defaults")
            return self._default_config()
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            return self._default_config()

    def _default_config(self):
        """Default configuration"""
        return {
            'motors': {
                'conveyor_speed': 0.5,
                'station_speed': 0.4,
                'corner_speed': 0.7
            },
            'stations': {
                'station1_process_time': 5,
                'station2_process_time': 7
            },
            'corners': {
                'extend_time': 1.5,
                'retract_time': 1.5,
                'final_approach_delay': 0.5,
                'handshake_timeout': 5.0
            },
            'cep': {
                'fusion_window': 2.0,
                'expiry_timeout': 5.0
            },
            'mqtt': {
                'broker_host': 'localhost',
                'broker_port': 1883
            },
            'logging': {
                'event_file': 'data/events.csv'
            }
        }

    def start(self):
        """Start the system"""
        self.logger.info("=" * 60)
        self.logger.info("STARTING MANUFACTURING SYSTEM")
        self.logger.info("=" * 60)

        # Start NFC producer threads
        self.logger.info("Starting NFC reader threads...")
        self.nfc1_thread.start()
        self.nfc2_thread.start()

        # Start CEP consumer thread
        self.logger.info("Starting CEP consumer...")
        self.cep_consumer.start()

        # Start monitoring thread if InfluxDB is connected
        if self.influx_writer and self.influx_writer.connected:
            self.logger.info("Starting InfluxDB monitoring...")
            self._start_monitoring_thread()

        self.logger.info("=" * 60)
        self.logger.info("SYSTEM RUNNING")
        self.logger.info("=" * 60)

    def stop(self):
        """Stop the system"""
        self.logger.info("=" * 60)
        self.logger.info("STOPPING MANUFACTURING SYSTEM")
        self.logger.info("=" * 60)

        # Stop monitoring thread
        if hasattr(self, '_monitoring_thread'):
            self.logger.info("Stopping monitoring thread...")
            self._stop_monitoring = True
            if self._monitoring_thread.is_alive():
                self._monitoring_thread.join(timeout=2)

        # Stop CEP consumer
        self.logger.info("Stopping CEP consumer...")
        self.cep_consumer.stop()
        self.cep_consumer.join(timeout=2)

        # Stop NFC threads
        self.logger.info("Stopping NFC readers...")
        self.nfc1_thread.stop()
        self.nfc2_thread.stop()
        self.nfc1_thread.join(timeout=2)
        self.nfc2_thread.join(timeout=2)

        # Stop sensor reader
        self.logger.info("Stopping sensor reader...")
        self.sensors.stop()

        # Stop FSMs (cancel any timers)
        self.logger.info("Stopping FSMs...")
        self.station1.stop()
        self.station2.stop()
        for corner in self.corners:
            corner.stop()

        # Stop all motors
        self.motors.stop_all()

        # Cleanup
        if self.influx_writer:
            self.influx_writer.cleanup()
        self.sensors.cleanup()
        self.mqtt.cleanup()

        # Print final KPIs
        self.data_logger.print_kpis()

        # Print CEP statistics
        stats = self.cep_consumer.get_statistics()
        self.logger.info("=" * 60)
        self.logger.info("CEP STATISTICS")
        self.logger.info("=" * 60)
        self.logger.info(f"Fused events: {stats['fused_events']}")
        self.logger.info(f"Orphaned GPIO: {stats['orphaned_gpio']}")
        self.logger.info(f"Ghost NFC: {stats['ghost_nfc']}")
        self.logger.info("=" * 60)

        self.logger.info("=" * 60)
        self.logger.info("SYSTEM STOPPED")
        self.logger.info("=" * 60)

    def get_status(self):
        """Get system status"""
        return {
            'station1': self.station1.get_status(),
            'station2': self.station2.get_status(),
            'corners': [c.get_status() for c in self.corners],
            'cep_stats': self.cep_consumer.get_statistics(),
            'queue_sizes': {
                'gpio': self.gpio_queue.qsize(),
                'mcp': self.mcp_queue.qsize(),
                'nfc': self.nfc_queue.qsize()
            }
        }

    def _start_monitoring_thread(self):
        """
        Start background monitoring thread

        Publishes KPIs and system status to InfluxDB every 5 seconds
        """
        import threading

        def monitoring_loop():
            self.logger.info("Monitoring thread started")

            while not getattr(self, '_stop_monitoring', False):
                try:
                    # Get current KPIs
                    kpis = self.data_logger.get_kpis()

                    # Write to InfluxDB
                    if self.influx_writer:
                        self.influx_writer.write_kpis(kpis)

                    # Get system status
                    status = self.get_status()

                    # Write system status
                    if self.influx_writer:
                        self.influx_writer.write_system_status(status)

                    # Get CEP statistics
                    cep_stats = self.cep_consumer.get_statistics()
                    if self.influx_writer:
                        self.influx_writer.write_cep_stats(cep_stats)

                    # Sleep for 5 seconds
                    time.sleep(5)

                except Exception as e:
                    self.logger.error(f"Monitoring thread error: {e}")
                    time.sleep(5)

            self.logger.info("Monitoring thread stopped")

        self._stop_monitoring = False
        self._monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
        self._monitoring_thread.start()
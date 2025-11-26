"""
InfluxDB Writer - Real-Time Data Streaming for Grafana
Streams all manufacturing events and KPIs to InfluxDB
"""

import logging
import time
from threading import Lock
from datetime import datetime

try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS

    INFLUXDB_AVAILABLE = True
except ImportError:
    INFLUXDB_AVAILABLE = False
    logging.warning("InfluxDB library not available - install: pip install influxdb-client")


class InfluxDBWriter:
    """
    Writes manufacturing data to InfluxDB for Grafana visualization

    Data points:
    - Events: Individual manufacturing events (ENTER, EXIT, etc.)
    - KPIs: Aggregated metrics (throughput, utilization, etc.)
    - System Status: Overall system state
    - Sensor Events: Raw sensor triggers
    - CEP Statistics: Event fusion metrics
    """

    def __init__(self, config):
        self.logger = logging.getLogger("InfluxDB")
        self.config = config
        self.lock = Lock()

        self.client = None
        self.write_api = None
        self.connected = False

        # Check if InfluxDB is configured
        if not INFLUXDB_AVAILABLE:
            self.logger.info("InfluxDB library not installed")
            return

        if 'influxdb' not in config:
            self.logger.info("InfluxDB not configured in config.yaml")
            return

        self._connect()

    def _connect(self):
        """Connect to InfluxDB"""
        try:
            url = self.config['influxdb']['url']
            token = self.config['influxdb']['token']
            org = self.config['influxdb']['org']

            self.logger.info(f"Connecting to InfluxDB: {url}")

            self.client = InfluxDBClient(url=url, token=token, org=org)
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

            # Test connection
            health = self.client.health()
            if health.status == "pass":
                self.connected = True
                self.logger.info(f"✓ Connected to InfluxDB: {url}")
                self.logger.info(f"  Organization: {org}")
                self.logger.info(f"  Bucket: {self.config['influxdb']['bucket']}")
            else:
                self.logger.error("InfluxDB health check failed")

        except Exception as e:
            self.logger.error(f"Failed to connect to InfluxDB: {e}")
            self.logger.error("Grafana dashboards will not receive data")
            self.client = None

    def write_event(self, part_id, station_id, activity, additional_fields=None):
        """
        Write manufacturing event to InfluxDB

        Measurement: "manufacturing_events"
        Tags: station_id, activity
        Fields: part_id, any additional fields
        """
        if not self.connected:
            return

        try:
            point = Point("manufacturing_events") \
                .tag("station_id", station_id) \
                .tag("activity", activity) \
                .field("part_id", part_id)

            # Add any additional fields
            if additional_fields:
                for key, value in additional_fields.items():
                    if isinstance(value, (int, float)):
                        point.field(key, float(value))
                    elif isinstance(value, str):
                        point.field(key, value)

            with self.lock:
                self.write_api.write(
                    bucket=self.config['influxdb']['bucket'],
                    org=self.config['influxdb']['org'],
                    record=point
                )

            self.logger.debug(f"Event written: {station_id}_{activity}")

        except Exception as e:
            self.logger.debug(f"Failed to write event: {e}")

    def write_kpis(self, kpis_dict):
        """
        Write multiple KPIs to InfluxDB

        Measurement: "manufacturing_kpis"
        Tags: kpi_name
        Fields: value
        """
        if not self.connected:
            return

        try:
            points = []

            for kpi_name, value in kpis_dict.items():
                if isinstance(value, (int, float)):
                    point = Point("manufacturing_kpis") \
                        .tag("kpi_name", kpi_name) \
                        .field("value", float(value)) \
                        .time(datetime.utcnow(), WritePrecision.NS)
                    points.append(point)

            if points:
                with self.lock:
                    self.write_api.write(
                        bucket=self.config['influxdb']['bucket'],
                        org=self.config['influxdb']['org'],
                        record=points
                    )

                self.logger.debug(f"Wrote {len(points)} KPIs to InfluxDB")

        except Exception as e:
            self.logger.debug(f"Failed to write KPIs: {e}")

    def write_station_state(self, station_id, state, part_id=None, additional_fields=None):
        """
        Write station state change to InfluxDB

        Measurement: "station_states"
        Tags: station_id, state
        Fields: part_id, additional data
        """
        if not self.connected:
            return

        try:
            point = Point("station_states") \
                .tag("station_id", station_id) \
                .tag("state", state)

            if part_id:
                point.field("part_id", part_id)

            # Add state as numeric field for graphing
            state_value = {
                'IDLE': 0,
                'ENTERING': 1,
                'PROCESSING': 2,
                'EXITING': 3,
                'BLOCKED': 4
            }.get(state, 0)
            point.field("state_value", state_value)

            if additional_fields:
                for key, value in additional_fields.items():
                    if isinstance(value, (int, float)):
                        point.field(key, float(value))

            with self.lock:
                self.write_api.write(
                    bucket=self.config['influxdb']['bucket'],
                    org=self.config['influxdb']['org'],
                    record=point
                )

        except Exception as e:
            self.logger.debug(f"Failed to write station state: {e}")

    def write_corner_state(self, corner_id, state, additional_fields=None):
        """
        Write corner state to InfluxDB

        Measurement: "corner_states"
        Tags: corner_id, state
        """
        if not self.connected:
            return

        try:
            point = Point("corner_states") \
                .tag("corner_id", corner_id) \
                .tag("state", state)

            # Add state as numeric field
            state_value = {
                'IDLE': 0,
                'FINAL_APPROACH': 1,
                'READY_TO_PUSH': 2,
                'EXTENDING': 3,
                'PUSHING': 4,
                'WAITING_FOR_CONFIRMATION': 5,
                'RETRACTING': 6
            }.get(state, 0)
            point.field("state_value", state_value)

            if additional_fields:
                for key, value in additional_fields.items():
                    if isinstance(value, (int, float)):
                        point.field(key, float(value))

            with self.lock:
                self.write_api.write(
                    bucket=self.config['influxdb']['bucket'],
                    org=self.config['influxdb']['org'],
                    record=point
                )

        except Exception as e:
            self.logger.debug(f"Failed to write corner state: {e}")

    def write_sensor_event(self, barrier_id, location_type, location_id):
        """
        Write raw sensor event to InfluxDB

        Measurement: "sensor_events"
        Tags: barrier_id, location_type, location_id
        """
        if not self.connected:
            return

        try:
            point = Point("sensor_events") \
                .tag("barrier_id", barrier_id) \
                .tag("location_type", location_type) \
                .tag("location_id", str(location_id)) \
                .field("trigger", 1)  # Binary indicator

            with self.lock:
                self.write_api.write(
                    bucket=self.config['influxdb']['bucket'],
                    org=self.config['influxdb']['org'],
                    record=point
                )

        except Exception as e:
            self.logger.debug(f"Failed to write sensor event: {e}")

    def write_cep_stats(self, stats):
        """
        Write CEP statistics to InfluxDB

        Measurement: "cep_statistics"
        Fields: fused_events, orphaned_gpio, ghost_nfc, etc.
        """
        if not self.connected:
            return

        try:
            point = Point("cep_statistics")

            for key, value in stats.items():
                if isinstance(value, (int, float)):
                    point.field(key, int(value))

            # Calculate fusion rate
            if stats.get('total_gpio', 0) > 0:
                fusion_rate = (stats.get('fused_events', 0) / stats['total_gpio']) * 100
                point.field("fusion_rate_pct", fusion_rate)

            with self.lock:
                self.write_api.write(
                    bucket=self.config['influxdb']['bucket'],
                    org=self.config['influxdb']['org'],
                    record=point
                )

        except Exception as e:
            self.logger.debug(f"Failed to write CEP stats: {e}")

    def write_system_status(self, status):
        """
        Write overall system status

        Measurement: "system_status"
        Fields: Various status indicators
        """
        if not self.connected:
            return

        try:
            point = Point("system_status")

            # Queue sizes
            if 'queue_sizes' in status:
                for queue_name, size in status['queue_sizes'].items():
                    point.field(f"queue_{queue_name}", int(size))

            # Station states
            if 'station1' in status:
                point.field("station1_busy", 1 if status['station1']['state'] != 'IDLE' else 0)
            if 'station2' in status:
                point.field("station2_busy", 1 if status['station2']['state'] != 'IDLE' else 0)

            # System health
            point.field("system_healthy", 1)

            with self.lock:
                self.write_api.write(
                    bucket=self.config['influxdb']['bucket'],
                    org=self.config['influxdb']['org'],
                    record=point
                )

        except Exception as e:
            self.logger.debug(f"Failed to write system status: {e}")

    def cleanup(self):
        """Cleanup InfluxDB connection"""
        if self.client:
            try:
                self.client.close()
                self.logger.info("InfluxDB connection closed")
            except:
                pass
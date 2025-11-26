"""
MQTT Handler
Publishes events and data to MQTT broker
"""

import logging
import json
import time
from threading import Lock

try:
    import paho.mqtt.client as mqtt

    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    logging.warning("MQTT library not available")


class MQTTHandler:
    """
    Handles MQTT communication
    Publishes events to MQTT broker for Node-RED processing
    """

    def __init__(self, broker_host="localhost", broker_port=1883):
        """
        Initialize MQTT handler

        broker_host: MQTT broker hostname
        broker_port: MQTT broker port
        """
        self.logger = logging.getLogger("MQTT")
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.lock = Lock()
        self.connected = False
        self.client = None

        if MQTT_AVAILABLE:
            try:
                # Create MQTT client
                self.client = mqtt.Client()
                self.client.on_connect = self._on_connect
                self.client.on_disconnect = self._on_disconnect

                # Connect to broker
                self.logger.info(f"Connecting to MQTT broker: {broker_host}:{broker_port}")
                self.client.connect(broker_host, broker_port, 60)

                # Start network loop in background for communication
                self.client.loop_start()

            except Exception as e:
                self.logger.error(f"Failed to connect to MQTT broker: {e}")
                self.client = None
        else:
            self.logger.warning("MQTT not available - events will not be published")

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker"""
        if rc == 0: # Successful connection
            self.connected = True
            self.logger.info("Connected to MQTT broker")
        else:
            self.logger.error(f"Connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker"""
        self.connected = False
        if rc != 0:
            self.logger.warning("Unexpected disconnection")

    def publish_event(self, part_id, station_id, activity):
        """
        Publish an event

        part_id: Part ID
        station_id: Station ID (S1, S2, C1, etc.)
        activity: Activity type (ENTER, EXIT, etc.)
        """
        if not self.client or not self.connected:
            return

        # Create event message
        event = {
            'timestamp': time.time(),
            'part_id': part_id,
            'station_id': station_id,
            'activity': activity
        }

        # Publish to topic
        topic = f"manufacturing/events/{station_id}"
        try:
            with self.lock:
                # Publish with QoS 1 for guaranteed delivery
                self.client.publish(topic, json.dumps(event), qos=1)
                self.logger.debug(f"Published: {topic} -> {event}")
        except Exception as e:
            self.logger.error(f"Failed to publish: {e}")

    def publish_kpi(self, kpi_name, value):
        """
        Publish a KPI value

        kpi_name: KPI name (e.g., "throughput", "utilization")
        value: KPI value
        """
        if not self.client or not self.connected:
            return

        # Create KPI message
        kpi = {
            'timestamp': time.time(),
            'kpi': kpi_name,
            'value': value
        }

        # Publish to KPI topic
        topic = f"manufacturing/kpis/{kpi_name}"
        try:
            with self.lock:
                # Publish with QoS 0 for best-effort delivery
                self.client.publish(topic, json.dumps(kpi), qos=0)
                self.logger.debug(f"Published KPI: {kpi_name} = {value}")
        except Exception as e:
            self.logger.error(f"Failed to publish KPI: {e}")

    def cleanup(self):
        """Cleanup MQTT connection"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.logger.info("MQTT disconnected")
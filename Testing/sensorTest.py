import logging
import queue
import time
from sensor_reader import SensorReader  # adjust import path if necessary

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

def main():
    # Queues to receive events
    gpio_queue = queue.Queue()
    mcp_queue = queue.Queue()

    # Initialize sensor reader
    sensor_reader = SensorReader(gpio_queue=gpio_queue, mcp_queue=mcp_queue, simulation=False)

    try:
        logging.info("SensorReader started. Press Ctrl+C to exit.")

        while True:
            # Process GPIO events
            try:
                event = gpio_queue.get_nowait()
                logging.info(f"GPIO Event: {event}")
            except queue.Empty:
                pass

            # Process MCP events
            try:
                event = mcp_queue.get_nowait()
                logging.info(f"MCP Event: {event}")
            except queue.Empty:
                pass

            # Sleep briefly to reduce CPU usage
            time.sleep(0.01)

    except KeyboardInterrupt:
        logging.info("Stopping test...")

    finally:
        sensor_reader.cleanup()
        logging.info("SensorReader stopped.")

if __name__ == "__main__":
    main()


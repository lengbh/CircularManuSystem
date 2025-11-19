## CircularManuSystem
The repository of a lab-scale 2-station closed-loop manufacturing system. 

*developed by Nikolaos, Bohan*

## Project Overview

This project implements a lab-scale manufacturing system with two processing stations connected in a closed loop using Fischertechnik components and Raspberry Pi control. The system is designed to demonstrate key concepts in automated manufacturing including:

- Part tracking through RFID/NFC technology
- Queue management and buffer behavior
- Real-time process monitoring
- Key performance indicator (KPI) calculation
- Data collection and visualization

## System Architecture

```mermaid
---
config:
  layout: elk
---
classDiagram
    direction TB
    class SystemManager {
        +config
        +gpio_queue
        +mcp_queue
        +nfc_queue
        +fsm_map
        +start()
        +stop()
        +monitor_health()
        +log_alerts()
    }
    class CEPConsumer {
        -pending_gpio_events
        -pending_nfc_events
        +run()
        -_consume_events()
        -_fuse_events()
        -_expire_events()
        -_deliver_event()
    }
    class SensorReader {
        <<Producer>>
        -gpio_queue
        -mcp_queue
        -_setup_gpio_interrupts()
        -_gpio_callback()
        -_setup_mcp_polling()
        -_mcp_poll_loop()
    }
    class NFCReaderThread {
        <<Producer>>
        -nfc_queue
        +run()
        -_blocking_read_tag()
    }
    class StationController {
        <<PassiveFSM>>
        -state
        -current_part
        +process_event(event)
        -_handle_idle()
        -_handle_entering()
        -_handle_processing()
        -_handle_exiting()
    }
    class CornerController {
        <<PassiveFSM>>
        -state
        -handshake_timeout
        +process_event(event)
        -_handle_idle()
        -_handle_extending()
        -_handle_waiting_for_confirmation()
        -_handle_retracting()
    }
    class MotorController {
        -hat1, hat2
        +set_speed(motor_num, speed)
        +stop(motor_num)
        +stop_all()
    }
    class CollisionManager {
        -corners_occupied
        -corners_waiting_handshake
        +request_corner(corner_num)
        +release_corner(corner_num)
        +is_conveyor_safe_to_stop(motor_num)
    }
    class DataLogger {
        -log_file
        +log_event(part_id, station_id, activity)
        +get_kpis()
    }
    class MQTTHandler {
        +publish_event(part_id, station_id, activity)
        +publish_kpi(kpi_name, value)
    }
    SystemManager "1" *-- "1" CEPConsumer : manages
    SystemManager "1" *-- "1" SensorReader : manages
    SystemManager "1" *-- "2" NFCReaderThread : manages
    SystemManager "1" *-- "2" StationController : manages
    SystemManager "1" *-- "4" CornerController : manages
    SystemManager "1" *-- "1" MotorController : manages
    SystemManager "1" *-- "1" CollisionManager : manages
    SystemManager "1" *-- "1" DataLogger : manages
    SystemManager "1" *-- "1" MQTTHandler : manages
    SensorReader ..> CEPConsumer : feeds via queues
    NFCReaderThread ..> CEPConsumer : feeds via queues
    CEPConsumer --> StationController : calls process_event()
    CEPConsumer --> CornerController : calls process_event()
    StationController ..> MotorController : uses
    StationController ..> DataLogger : uses
    CornerController ..> MotorController : uses
    CornerController ..> CollisionManager : uses
    CornerController ..> SensorReader : uses helper functions
    DataLogger ..> MQTTHandler : uses


```


## Production Concept

The system simulates a small manufacturing cell that could represent various real-world processes:

### Manufacturing Scenario 1: Electronics Assembly

- **Station 1**: Component Placement
  Parts are positioned precisely and components are placed onto a circuit board.
  
- **Station 2**: Quality Inspection
  Completed assemblies are inspected for defects using vision systems.

### Manufacturing Scenario 2: Machining Operations

- **Station 1**: Milling Operation
  Raw parts are milled to create specific features or shapes.
  
- **Station 2**: Finishing and Deburring
  Machined parts have sharp edges removed and surfaces smoothed.

### Manufacturing Scenario 3: Packaging Line

- **Station 1**: Product Filling
  Containers are filled with a specified amount of product.
  
- **Station 2**: Labeling and Sealing
  Filled containers are labeled and sealed for shipment.

## System Features

- **Closed-Loop Material Flow**: Parts continuously circulate through the system
- **Software Queuing**: Parts wait at station entrance if the processing position is occupied
- **NFC Tag Identification**: Each part is uniquely
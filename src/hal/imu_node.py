import time
import math
import zmq
from zmq.utils.monitor import recv_monitor_message
from pydantic import ValidationError

# System imports
from core.models import ImuMessage
from core.messaging import Topics, get_zmq_url
from hal.drivers.wt901_driver import WT901Driver

class ImuNode:
    def __init__(self, serial_port="COM3", baud_rate=9600, mag_declination=0.0, user_offset=0.0):
        """
        Connects the WT901 IMU to the internal ZMQ data bus.
        """
        self.mag_declination = mag_declination
        self.user_offset = user_offset
        
        # QGC / MAVLink NED body frame mapping (copied from old parser)
        self.QGC_AXIS_MAP = {
            "mx_sign": 1,      # magnetometer X
            "my_sign": 1,      # magnetometer Y
            "mz_sign": 1       # magnetometer Z
        }

        # ZMQ Context & Socket Setup
        self.context = zmq.Context()
        self.pub_socket = self.context.socket(zmq.PUB)
        
        bus_url = get_zmq_url() # Gets the central IPC/TCP URL
        self.pub_socket.connect(bus_url)
        print(f"[IMU Node] Publisher connected to ZMQ Bus: {bus_url}")

        # Instantiate Driver and register callback
        self.driver = WT901Driver(
            serial_port=serial_port, 
            baud_rate=baud_rate, 
            on_data_callback=self.publish_imu_data
        )

    def calculate_mag_heading(self, mx, my):
        """
        Returns magnetic compass heading [0,360) degrees from raw mag values, 
        applying declination and user offset.
        """
        mx_mapped = mx * self.QGC_AXIS_MAP.get("mx_sign", 1)
        my_mapped = my * self.QGC_AXIS_MAP.get("my_sign", 1)
        
        # WT901C-TTL: heading = atan2(my, mx) (sensor X forward, Y right)
        heading_rad = math.atan2(my_mapped, mx_mapped)
        heading_deg = math.degrees(heading_rad)
        
        # Normalize to [0,360)
        heading_deg = (heading_deg + 360.0) % 360.0
        
        # Apply declination and user offset
        heading_deg = (heading_deg + self.mag_declination + self.user_offset) % 360.0
        return heading_deg

    def publish_imu_data(self, raw_data_dict):
        """
        Driver invokes this every time an 'Angles (0x53)' frame is fully parsed.
        """
        ts = time.time()
        
        # Calculate heading
        m_heading = self.calculate_mag_heading(raw_data_dict["mx"], raw_data_dict["my"])

        try:
            # Map into Pydantic Model
            msg = ImuMessage(
                timestamp=ts,
                roll=raw_data_dict["roll"],
                pitch=raw_data_dict["pitch"],
                yaw=raw_data_dict["yaw"],
                ax=raw_data_dict["ax"],
                ay=raw_data_dict["ay"],
                az=raw_data_dict["az"],
                wx=raw_data_dict["wx"],
                wy=raw_data_dict["wy"],
                wz=raw_data_dict["wz"],
                mx=raw_data_dict["mx"],
                my=raw_data_dict["my"],
                mz=raw_data_dict["mz"],
                temp=raw_data_dict["temp"],
                mag_heading=m_heading
            )
            
            # Serialize
            json_str = msg.model_dump_json()
            
            # Publish!
            # Format: 'topic payload'
            self.pub_socket.send_string(f"{Topics.SENSOR_IMU} {json_str}")
            
        except ValidationError as e:
            print(f"[IMU Node] Data validation error dropping frame: {e}")

    def run(self):
        print("[IMU Node] Starting driver thread...")
        self.driver.start()
        try:
            while True:
                # Node loop simply sleeps, the worker thread triggers the callback
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[IMU Node] Keyboard Interrupt detected. Shutting down...")
            self.shutdown()

    def shutdown(self):
        self.driver.stop()
        self.pub_socket.close()
        self.context.term()
        print("[IMU Node] Shutdown complete.")

if __name__ == '__main__':
    # Start the node (adjust COM port for Windows /dev/ttyUSB0 for linux)
    node = ImuNode(serial_port="COM3", baud_rate=9600, mag_declination=2.5)
    node.run()

# One island sensor's health (an item of IslandSensorHealth).

uint8 SENSOR_CAMERA = 0
uint8 SENSOR_RADAR = 1
uint8 SENSOR_ULTRASONIC = 2
uint8 SENSOR_IMU_GNSS = 3
uint8 SENSOR_LIDAR = 4

uint8 CAUSE_NONE = 0
uint8 CAUSE_DIRT = 1
uint8 CAUSE_SPRAY = 2
uint8 CAUSE_FOG = 3
uint8 CAUSE_LOW_SUN = 4
uint8 CAUSE_INTERFERENCE = 5
uint8 CAUSE_FRAME_RATE = 6
uint8 CAUSE_SILENT = 7

uint8 sensor
bool fitted
bool available
bool blocked
uint8 degradation_cause

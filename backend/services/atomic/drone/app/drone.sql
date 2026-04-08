CREATE TABLE IF NOT EXISTS drones (
    id SERIAL PRIMARY KEY,
    battery_level INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL, --('available', 'in-flight', 'charging', 'maintenance')
	current_longitude FLOAT NOT NULL,
	current_latitude FLOAT NOT NULL
);


CREATE TABLE IF NOT EXISTS telemetry (
	id SERIAL PRIMARY KEY,
	drone_id INTEGER NOT NULL,
	timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	
	FOREIGN KEY (drone_id) REFERENCES drones(id) ON DELETE CASCADE
);

INSERT INTO drones (id, battery_level, status, current_longitude, current_latitude) VALUES
(1,100, 'available', -122.4194, 37.7749),
(2,100, 'maintenance', -122.4194, 37.7749),
(3,100, 'available', -122.4194, 37.7749)
ON CONFLICT (id) DO NOTHING;



CREATE INDEX IF NOT EXISTS idx_telemetry_drone_id ON telemetry(drone_id);
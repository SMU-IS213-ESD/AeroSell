-- Create separate databases for each atomic service
CREATE DATABASE document_db;
CREATE DATABASE drone_db;
CREATE DATABASE error_db;
CREATE DATABASE flight_db;
CREATE DATABASE operations_support_db;
CREATE DATABASE order_db;
CREATE DATABASE payment_db;
CREATE DATABASE user_db;
CREATE DATABASE weather_db;

-- Grant privileges to existing user `user` for each database
GRANT ALL PRIVILEGES ON DATABASE document_db TO "user";
GRANT ALL PRIVILEGES ON DATABASE drone_db TO "user";
GRANT ALL PRIVILEGES ON DATABASE error_db TO "user";
GRANT ALL PRIVILEGES ON DATABASE flight_db TO "user";
GRANT ALL PRIVILEGES ON DATABASE operations_support_db TO "user";
GRANT ALL PRIVILEGES ON DATABASE order_db TO "user";
GRANT ALL PRIVILEGES ON DATABASE payment_db TO "user";
GRANT ALL PRIVILEGES ON DATABASE user_db TO "user";
GRANT ALL PRIVILEGES ON DATABASE weather_db TO "user";

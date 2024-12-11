##W_T_retrieval unit testing description

The unit tests collectively validate the critical functionality of the W_T_retrieval script by focusing on its individual components
and their integration. Below is a consolidated description of the validations performed by the unit tests:

#get_temperatures Function:

Verifies that the function correctly parses temperature data from the sensors command output under various scenarios, including:
-Valid output with properly formatted temperature readings.
-Empty or invalid command output.
-Command execution errors such as CalledProcessError.

#get_power_consumption Function:

Confirms accurate power consumption calculations by reading energy values from system files under real-world scenarios:
-Valid energy file readings, ensuring all values are non-negative.
-Missing or corrupt energy files, validating default or fallback behavior.
-Boundary conditions, such as extreme energy values, ensuring calculations remain within realistic limits.

#send_to_influxdb Function:

Ensures the function correctly formats and transmits temperature and power data to the InfluxDB server:
-Properly formatted payload and headers for valid data.
-Graceful handling of empty data, ensuring no unintended errors occur.
-Response handling for cases like server errors or authentication failures.

#Main Loop Integration:

-Verifies the seamless interaction between get_temperatures, get_power_consumption, and send_to_influxdb in the script's main execution loop:
-Ensures successful iterations with valid data.
-Validates handling of empty or missing data, including logging appropriate error messages.
-Confirms the script handles KeyboardInterrupt gracefully for termination.

#Performance and Edge Cases:

Tests the script's robustness and performance under stress:
-High-frequency iterations with rapid data retrieval and transmission.
-Handling large datasets for temperature and power metrics, ensuring no failures.
-Behavior when encountering an invalid InfluxDB URL, validating error handling.

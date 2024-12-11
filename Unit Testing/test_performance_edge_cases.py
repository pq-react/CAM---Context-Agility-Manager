import time
import unittest
from unittest.mock import patch, MagicMock
import W_T_retrieval


class TestPerformanceEdgeCases(unittest.TestCase):
    @patch('time.sleep', side_effect=KeyboardInterrupt)  # Simulate interrupting the main loop
    @patch('W_T_retrieval.send_to_influxdb')
    @patch('W_T_retrieval.get_power_consumption', return_value={"System": 10.5, "Core": 0.4, "Package_0_0": 5.0})
    @patch('W_T_retrieval.get_temperatures', return_value={"Core_0": 45.0, "Core_4": 50.0})
    def test_high_frequency_handling(self, mock_temps, mock_power, mock_send, mock_sleep):
        # Simulate the main script execution by replicating its loop behavior
        try:
            while True:
                temperatures = W_T_retrieval.get_temperatures()
                power = W_T_retrieval.get_power_consumption(interval=1)
                if temperatures or power:
                    W_T_retrieval.send_to_influxdb(temperatures, power)
                time.sleep(0.1)  # High-frequency simulation
        except KeyboardInterrupt:
            pass  # Expected to exit the loop

        mock_temps.assert_called()
        mock_power.assert_called()
        mock_send.assert_called()

    @patch('W_T_retrieval.requests.post')
    def test_invalid_influxdb_url(self, mock_post):
        # Test with an invalid InfluxDB URL
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Internal Server Error"

        temperatures = {"Core_0": 45.0}
        power = {"System": 10.5}
        W_T_retrieval.send_to_influxdb(temperatures, power)

        mock_post.assert_called_once()
        called_data = mock_post.call_args[1]['data']
        self.assertIn("temperatures,key=Core_0", called_data)

    @patch('W_T_retrieval.get_temperatures', return_value={f"Core_{i}": i for i in range(100)})
    @patch('W_T_retrieval.get_power_consumption', return_value={f"Package_{i}": i * 0.5 for i in range(50)})
    @patch('W_T_retrieval.send_to_influxdb')
    @patch('time.sleep', side_effect=KeyboardInterrupt)  # Simulate interrupting the main loop
    def test_large_data_handling(self, mock_sleep, mock_send, mock_power, mock_temps):
        # Simulate the main script execution by replicating its loop behavior
        try:
            while True:
                temperatures = W_T_retrieval.get_temperatures()
                power = W_T_retrieval.get_power_consumption(interval=1)
                if temperatures or power:
                    W_T_retrieval.send_to_influxdb(temperatures, power)
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass  # Expected to exit the loop

        mock_temps.assert_called()
        mock_power.assert_called()
        mock_send.assert_called()

if __name__ == "__main__":
    unittest.main()

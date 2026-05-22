import unittest
import W_T_retrieval
from unittest.mock import patch


class TestPerformanceEdgeCases(unittest.TestCase):
    @patch('W_T_retrieval.time.sleep')  # high-frequency: don't actually wait
    @patch('W_T_retrieval.send_to_influxdb')
    @patch('W_T_retrieval.get_power_consumption', return_value={"System": 10.5, "Core": 0.4, "Package_0_0": 5.0})
    @patch('W_T_retrieval.get_temperatures', return_value={"Core_0": 45.0, "Core_4": 50.0})
    def test_high_frequency_handling(self, mock_temps, mock_power, mock_send, mock_sleep):
        # Many fast iterations through the real loop body.
        W_T_retrieval.main_loop(iterations=10, interval=0)

        self.assertEqual(mock_temps.call_count, 10)
        self.assertEqual(mock_power.call_count, 10)
        self.assertEqual(mock_send.call_count, 10)

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
    @patch('W_T_retrieval.time.sleep')
    def test_large_data_handling(self, mock_sleep, mock_send, mock_power, mock_temps):
        # Large payloads through one full loop pass.
        W_T_retrieval.main_loop(iterations=1, interval=0)

        mock_temps.assert_called_once()
        mock_power.assert_called_once()
        mock_send.assert_called_once()
        # The large dicts must be forwarded intact.
        temps_arg, power_arg = mock_send.call_args[0]
        self.assertEqual(len(temps_arg), 100)
        self.assertEqual(len(power_arg), 50)

if __name__ == "__main__":
    unittest.main()

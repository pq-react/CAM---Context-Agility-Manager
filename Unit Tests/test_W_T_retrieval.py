import unittest
from unittest.mock import patch, MagicMock
import W_T_retrieval


class TestWTRetrieval(unittest.TestCase):
    @patch('W_T_retrieval.get_temperatures', return_value={"Core_0": 50.0})
    @patch('W_T_retrieval.get_power_consumption', return_value={"System": 50.0})
    @patch('W_T_retrieval.send_to_influxdb')
    @patch('time.sleep', side_effect=KeyboardInterrupt)  # Simulate exiting the loop
    def test_main_loop(self, mock_sleep, mock_send, mock_power, mock_temp):
        with self.assertRaises(KeyboardInterrupt):  # Expect loop to terminate with KeyboardInterrupt
            # Simulate the __main__ loop
            exec(
                """
import time
while True:
    temperatures = W_T_retrieval.get_temperatures()
    power = W_T_retrieval.get_power_consumption(interval=1)

    if temperatures or power:
        for key, value in temperatures.items():
            print(f"{key}: {value}°C")
        for key, power_value in power.items():
            print(f"Power consumption ({key}): {power_value} W")
        W_T_retrieval.send_to_influxdb(temperatures, power)
    else:
        print("Failed to retrieve temperatures or power consumption.")

    time.sleep(0.5)
                """
            )

        # Ensure all mocked functions were called
        mock_temp.assert_called()
        mock_power.assert_called()
        mock_send.assert_called()


if __name__ == '__main__':
    unittest.main()

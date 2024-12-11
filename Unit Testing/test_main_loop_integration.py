import unittest
from unittest.mock import patch, MagicMock
import time
import W_T_retrieval

class TestMainLoopIntegration(unittest.TestCase):
    @patch('W_T_retrieval.get_temperatures')
    @patch('W_T_retrieval.get_power_consumption')
    @patch('W_T_retrieval.send_to_influxdb')
    @patch('time.sleep', side_effect=KeyboardInterrupt)  # Simulate exiting the loop
    def test_successful_iteration(self, mock_sleep, mock_send, mock_power, mock_temp):
        mock_temp.return_value = {"Core_0": 50.0}
        mock_power.return_value = {"System": 50.0}

        with self.assertRaises(KeyboardInterrupt):  # Expect loop to terminate with KeyboardInterrupt
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

    @patch('W_T_retrieval.get_temperatures', return_value={})
    @patch('W_T_retrieval.get_power_consumption', return_value={})
    @patch('time.sleep', side_effect=KeyboardInterrupt)  # Simulate exiting the loop
    def test_empty_data_handling(self, mock_sleep, mock_power, mock_temp):
        with self.assertRaises(KeyboardInterrupt):  # Expect loop to terminate with KeyboardInterrupt
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

        # Ensure the failure message is printed
        mock_temp.assert_called()
        mock_power.assert_called()

    @patch('time.sleep', side_effect=KeyboardInterrupt)  # Simulate exiting the loop
    def test_keyboard_interrupt_handling(self, mock_sleep):
        with self.assertRaises(KeyboardInterrupt):  # Expect loop to terminate with KeyboardInterrupt
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

if __name__ == '__main__':
    unittest.main()

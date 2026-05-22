import unittest
from unittest.mock import patch
import W_T_retrieval


class TestMainLoopIntegration(unittest.TestCase):
    """Drive W_T_retrieval.main_loop() with a bounded iteration count.

    The collectors are mocked, so the loop is deterministic and never
    touches the `sensors` binary, the powercap sysfs, or the network.
    Previously these tests re-implemented the loop body inside exec()
    and broke out of `while True` by making time.sleep raise
    KeyboardInterrupt — which could escape the test process and exit it
    with code 130 on some interpreter/OS combinations.
    """

    @patch('W_T_retrieval.time.sleep')  # don't actually sleep between iterations
    @patch('W_T_retrieval.send_to_influxdb')
    @patch('W_T_retrieval.get_power_consumption')
    @patch('W_T_retrieval.get_temperatures')
    def test_successful_iteration(self, mock_temp, mock_power, mock_send, mock_sleep):
        mock_temp.return_value = {"Core_0": 50.0}
        mock_power.return_value = {"System": 50.0}

        W_T_retrieval.main_loop(iterations=1)

        # One full pass should have collected and forwarded the metrics.
        mock_temp.assert_called_once()
        mock_power.assert_called_once()
        mock_send.assert_called_once_with({"Core_0": 50.0}, {"System": 50.0})

    @patch('W_T_retrieval.time.sleep')
    @patch('W_T_retrieval.send_to_influxdb')
    @patch('W_T_retrieval.get_power_consumption', return_value={})
    @patch('W_T_retrieval.get_temperatures', return_value={})
    def test_empty_data_handling(self, mock_temp, mock_power, mock_send, mock_sleep):
        W_T_retrieval.main_loop(iterations=1)

        # With no data on either collector the loop must NOT post anything.
        mock_temp.assert_called_once()
        mock_power.assert_called_once()
        mock_send.assert_not_called()

    @patch('W_T_retrieval.time.sleep')
    @patch('W_T_retrieval.send_to_influxdb')
    @patch('W_T_retrieval.get_power_consumption', return_value={"System": 1.0})
    @patch('W_T_retrieval.get_temperatures', return_value={"Core_0": 40.0})
    def test_multiple_iterations(self, mock_temp, mock_power, mock_send, mock_sleep):
        W_T_retrieval.main_loop(iterations=3)

        # The bounded loop runs exactly `iterations` times.
        self.assertEqual(mock_temp.call_count, 3)
        self.assertEqual(mock_power.call_count, 3)
        self.assertEqual(mock_send.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 3)


if __name__ == '__main__':
    unittest.main()

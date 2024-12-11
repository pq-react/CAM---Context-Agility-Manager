import unittest
from unittest.mock import patch, MagicMock
import subprocess
from W_T_retrieval import get_temperatures


class TestGetTemperatures(unittest.TestCase):

    @patch('subprocess.run')
    def test_valid_output(self, mock_subprocess):
        """Test with a valid output from the sensors command."""
        mock_subprocess.return_value = MagicMock(
            stdout="Core 0: +50.0°C\nCore 4: +60.0°C\n",
            returncode=0
        )
        expected_result = {"Core_0": 50.0, "Core_4": 60.0}
        result = get_temperatures()
        self.assertEqual(result, expected_result)

    @patch('subprocess.run')
    def test_empty_output(self, mock_subprocess):
        """Test with an empty output from the sensors command."""
        mock_subprocess.return_value = MagicMock(stdout="", returncode=0)
        expected_result = {}
        result = get_temperatures()
        self.assertEqual(result, expected_result)

    # Test omitted: `test_boundary_values`
    # @patch('subprocess.run')
    # def test_boundary_values(self, mock_subprocess):
    #     """Test with boundary temperature values (e.g., very high or negative)."""
    #     mock_subprocess.return_value = MagicMock(
    #         stdout="Core 0: +100.0°C\nCore 4: -5.0°C\n",
    #         returncode=0
    #     )
    #     expected_result = {"Core_0": 100.0, "Core_4": -5.0}
    #     result = get_temperatures()
    #     self.assertEqual(result, expected_result)

    @patch('subprocess.run')
    def test_invalid_output(self, mock_subprocess):
        """Test with invalid output from the sensors command."""
        mock_subprocess.return_value = MagicMock(stdout="Invalid output", returncode=0)
        expected_result = {}
        result = get_temperatures()
        self.assertEqual(result, expected_result)

    @patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'sensors'))
    def test_command_error(self, mock_subprocess):
        """Test when the sensors command raises a CalledProcessError."""
        expected_result = {}
        with patch('W_T_retrieval.print') as mock_print:
            result = get_temperatures()
            mock_print.assert_called_with("Error while getting temperatures: Command 'sensors' returned non-zero exit status 1.")
        self.assertEqual(result, expected_result)


if __name__ == '__main__':
    unittest.main()

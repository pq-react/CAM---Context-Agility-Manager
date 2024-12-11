import unittest
from unittest.mock import patch
import W_T_retrieval


class TestSendToInfluxDB(unittest.TestCase):
    @patch("W_T_retrieval.requests.post")
    def test_valid_data(self, mock_post):
        # Mock a successful response
        mock_post.return_value.status_code = 204

        temps = {"Core_0": 50.0}
        power = {"System": 10.0}
        W_T_retrieval.send_to_influxdb(temps, power)

        # Validate the request was made with correct data
        expected_data = (
            "temperatures,key=Core_0 value=50.0\n"
            "power_consumption,key=System value=10.0\n"
        )
        mock_post.assert_called_once_with(
            W_T_retrieval.influxdb_url,
            headers={
                "Authorization": f"Token {W_T_retrieval.token}",
                "Content-Type": "text/plain; charset=utf-8",
            },
            params={
                "org": W_T_retrieval.org,
                "bucket": W_T_retrieval.bucket,
                "precision": "s",
            },
            data=expected_data,
        )

    @patch("W_T_retrieval.requests.post")
    def test_empty_data(self, mock_post):
        # Mock a successful response
        mock_post.return_value.status_code = 204

        # Pass empty dictionaries for temperature and power
        W_T_retrieval.send_to_influxdb({}, {})

        # Validate the request was made with empty data
        mock_post.assert_called_once_with(
            W_T_retrieval.influxdb_url,
            headers={
                "Authorization": f"Token {W_T_retrieval.token}",
                "Content-Type": "text/plain; charset=utf-8",
            },
            params={
                "org": W_T_retrieval.org,
                "bucket": W_T_retrieval.bucket,
                "precision": "s",
            },
            data="",  # Data should be an empty string
        )


if __name__ == "__main__":
    unittest.main()

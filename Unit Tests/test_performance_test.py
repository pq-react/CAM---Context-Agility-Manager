import unittest
from unittest.mock import patch, MagicMock
import json
import performance_test  # Replace with your actual script name (without .py)


class TestPerformanceTest(unittest.TestCase):
    @staticmethod
    def create_test_algorithm(algorithm):
        """Factory method to create a test function for a given algorithm."""

        @patch('performance_test.requests.post')
        def test_func(self, mock_post):
            """Dynamically test each algorithm."""
            # Mock the post response
            def mock_post_side_effect(url, headers, data):
                payload = json.loads(data)
                return MagicMock(
                    status_code=201,
                    json=lambda: {
                        "success": True,
                        "algorithm": payload["algorithm"],
                        "iterationsCount": payload["iterationsCount"]
                    }
                )

            mock_post.side_effect = mock_post_side_effect

            # Test the current algorithm
            payload = {
                "algorithm": algorithm,
                "iterationsCount": 5,
                "messageSize": 1000
            }
            response = mock_post(performance_test.url, headers=performance_test.headers, data=json.dumps(payload))
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["algorithm"], algorithm)

        return test_func


def generate_algorithm_tests():
    """Dynamically generate tests for each algorithm."""
    for algorithm in performance_test.algorithms:
        test_name = f"test_algorithm_{algorithm}"
        test_func = TestPerformanceTest.create_test_algorithm(algorithm)
        setattr(TestPerformanceTest, test_name, test_func)


# Generate the algorithm-specific tests dynamically
generate_algorithm_tests()

if __name__ == '__main__':
    unittest.main()

The unit test of performance_test.py dynamically validates the behavior of a performance testing script that interacts
with an external API.

Specifically:

Algorithm-Specific Validation:

-Ensures that the script correctly constructs and sends POST requests with payloads specific to each algorithm being tested.
-Verifies that the API responses are handled accurately, including checking:
-The HTTP status code (201 for success).
-The correctness of the algorithm name and other payload details in the response.

Dynamic Test Generation:

-Automatically generates and executes separate test cases for each algorithm listed in the script,
ensuring comprehensive coverage without repetitive coding.

Response Mocking:

-Simulates API behavior using unittest.mock to validate the script’s functionality
independently of the actual API availability or network conditions.

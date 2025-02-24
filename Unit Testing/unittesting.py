import unittest

def load_tests(loader, tests, pattern):
    # Create a test suite
    suite = unittest.TestSuite()

    # Add test cases from individual test files
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_get_temperatures'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_send_to_influxdb'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_main_loop_integration'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_get_power_consumption'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_performance_edge_cases'))

    return suite

if __name__ == "__main__":
    # Load all tests
    suite = load_tests()

    # Run the test suite
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

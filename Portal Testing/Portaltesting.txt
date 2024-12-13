#Locust Testing Tool for Portal Testing


Locust is a versatile load testing tool for simulating user behavior on web portals.
It allows you to test the performance and reliability of your system under various traffic loads
by simulating multiple users accessing and interacting with the portal.
With Locust, you can:

-Simulate user actions like logging in, accessing pages, and performing tasks.
-Monitor request performance, error rates, and system behavior.

##Steps to Install and Use Locust

1. Install Locust
Ensure Python (3.7 or newer) is installed.
Install Locust using pip:
```bash
pip install locust
```

2. Execute locust test
Make sure that the portal_test.py file is in the same directory and execute the following command:
```bash
locust -f portal_test.py --headless -u 100 -r 5 --run-time 30s
```
this will execute a load test five times simulating 100 users

This test includes several tasks such as accessing the home page , logging in , browsing dashboards ,
adding a new connection , and accessing the admin page (/admin). The primary goal of this test suite is to mimic
real-world user actions to identify bottlenecks, detect any performance degradation under increasing loads,
validate stability of critical features like login and dashboard access, measure response times for various user
actions, assess the portal’s scalability to handle concurrent users and traffic spikes, and ensure key functionalities
operate as expected under load. By running these tests, the development team can ensure the portal is robust, responsive,
and capable of handling the anticipated user base effectively. 

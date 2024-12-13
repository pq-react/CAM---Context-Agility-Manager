from locust import HttpUser, task, between

class PortalUser(HttpUser):
    # Define wait time between tasks to simulate realistic user behavior
    wait_time = between(1, 3)  # Random wait time between 1 to 3 seconds

    # Base host for the portal
    host = "http://1.1.1.57:3000"

    @task(2)  # Task with a weight of 2 (more frequent)
    def access_home(self):
        """Simulate accessing the home page."""
        self.client.get("/?orgId=1")

    @task(1)  # Task with a weight of 1 (less frequent)
    def login(self):
        """Simulate user login."""
        self.client.post("/login", json={
            "user": "admin",
            "password": "1234asdf"
        })

    @task(3)  # Task with a weight of 3
    def browse_dashboard(self):
        """Simulate accessing the dashboard list."""
        self.client.get("/dashboards")

    @task(1)  # Task with a weight of 1
    def add_new_connection(self):
        """Simulate adding a new connection."""
        self.client.get("/connections/add-new-connection")

    @task(1)  # Task with a weight of 1
    def access_admin_page(self):
        """Simulate accessing the administrator page."""
        self.client.get("/admin")

    def on_start(self):
        """Simulate a user login on start."""
        self.client.post("/login", json={
            "user": "admin",
            "password": "`1234asdf"
        })

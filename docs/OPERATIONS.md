# Local test operator guide

Use [Test deployment and acceptance testing with a coding agent](TEST_DEPLOYMENT.md)
for the current setup, workflow, troubleshooting, and PM acceptance checklist.
It supersedes earlier operator instructions about manual Save/Check readiness
buttons, order-name restrictions, and enabling paid labels.

The current app uses automatic readiness checks and ShipStation development labels
for configured accounts. USPS is selected by default. All order numbers can be
tested; live purchasing is disabled in this development workflow. With no credentials,
the app uses local Simulation.

Keep existing data and history. See the [backup and restore guide](../README.md#backup-and-restore)
before storage changes. Local mode has no user authentication and binds to loopback;
Google Cloud deployment remains a separate deployment phase.

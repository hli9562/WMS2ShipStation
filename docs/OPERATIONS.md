# Local test operator guide

Use [Test deployment and acceptance testing with a coding agent](TEST_DEPLOYMENT.md)
for the current setup, workflow, troubleshooting, and PM acceptance checklist.
It supersedes earlier operator instructions about manual Save/Check readiness
buttons, order-name restrictions, and enabling paid labels.

The app uses automatic readiness checks. Configured accounts use development labels
when `WMS_ENABLE_LIVE_PURCHASE=false`; setting it to `true` enables paid purchases
with a confirmation before each label. Keep it false while following the PM test
guide. With no credentials, the app uses local Simulation.

Keep existing data and history. See the [backup and restore guide](../README.md#backup-and-restore)
before storage changes. Local mode has no user authentication and binds to loopback;
Google Cloud deployment remains a separate deployment phase.

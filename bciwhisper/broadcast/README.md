# Broadcast layer ownership

This layer owns:

- BroadcastBus
- Go-Live lifecycle
- authenticated publisher
- Bun gateway process manager
- gateway health/admin client
- public telemetry handoff

It does **not** own microphone capture, DSP, recording, or GUI widgets.

Local sequence:

GO LIVE
-> spawn Bun gateway
-> health check
-> authenticate publisher
-> hello/ack
-> publish encoded audio
-> mark LIVE

STOP LIVE
-> stop publisher
-> drain/close stream
-> terminate local Bun gateway
-> mark OFFLINE

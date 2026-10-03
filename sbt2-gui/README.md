# sbt2-gui

Reserved for the sbt2 GUI.

The GUI reads the messages of [sbt2-protocol/](../sbt2-protocol) and connects to
a separately deployed [sbt2-backend/](../sbt2-backend) server over its
WebSocket. It never imports the backend, and it builds without Python or
Nautilus, so this folder holds no dependency on either.

No toolkit is chosen here yet.

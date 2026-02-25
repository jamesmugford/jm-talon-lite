-
settings():
    # Forward Talon key() through external backend when enabled
    user.key_forwarder_enabled = 1

    # Auto-arm control1 mouse forwarding on Talon startup
    user.control1_pointer_forwarder_autostart = 1

    # Log once when autostart is applied
    user.control1_pointer_forwarder_autostart_log = 1

    # Auto-start control1 gaze logger on Talon startup
    user.control1_gaze_logger_autostart = 0

    # Enable hiss mouse behavior on Talon startup
    user.hiss_mouse_autostart = 1

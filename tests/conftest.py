"""Project-wide pytest configuration.

The production application is headless Python plus an Electron renderer, so
test collection must not initialize a GUI runtime or require Qt dependencies.
"""

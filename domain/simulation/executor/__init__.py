"""Circuit-simulation execution boundary.

The application currently has one deliberate backend: ngspice. Import the
concrete classes from their modules so importing this package does not load a
native DLL or create process-global simulator state as a side effect.
"""

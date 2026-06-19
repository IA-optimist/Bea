"""
bea-sdk exceptions
"""
class BeaError(Exception):
    """Base exception for Bea SDK errors."""
    pass

class MissionError(BeaError):
    """Exception raised for mission-related errors."""
    pass

class MemoryError(BeaError):
    """Exception raised for memory-related errors."""
    pass

class AuthenticationError(BeaError):
    """Exception raised for authentication failures."""
    pass

class ConnectionError(BeaError):
    """Exception raised for connection failures."""
    pass

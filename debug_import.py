import sys
import os

# Add python folder to path
sys.path.insert(0, 'python')

print("Python:", sys.version)
print("Path:", sys.path[:3])
print()

# Try loading core directly
print("Trying to load fasteda_core...")
try:
    sys.path.insert(0, 'python/fasteda')
    import fasteda_core
    print("SUCCESS! Core loaded:", fasteda_core)
except ImportError as e:
    print("ImportError:", e)
except OSError as e:
    print("OSError (DLL missing?):", e)
except Exception as e:
    print("Error:", type(e).__name__, e)
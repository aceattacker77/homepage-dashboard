import os
import sys

# Tests import the status-api modules directly (they are scripts, not a package).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

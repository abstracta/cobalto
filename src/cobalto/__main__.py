"""python -m cobalto: the same as the cobalto command."""
import sys

from .cli import main

sys.exit(main())

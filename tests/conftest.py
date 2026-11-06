import os
import tempfile

# Must be set before tabby.config is imported anywhere.
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["SCAN_RATE_LIMIT_PER_MIN"] = "0"
os.environ["SHARE_RATE_LIMIT_PER_MIN"] = "0"

import pathlib
import subprocess
import tempfile
import unittest


class AllocationLogBudgetTests(unittest.TestCase):
    def test_signed_call_range_and_sampling_contract(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        source = root / "tests/test_allocation_log_budget.cpp"
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / "allocation-log-budget"
            subprocess.run(
                ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()

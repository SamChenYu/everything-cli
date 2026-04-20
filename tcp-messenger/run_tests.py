#!/usr/bin/env python3
"""
Test runner for TCP Messenger unit tests
Runs all unit tests and provides a summary
"""
import unittest
import sys
import os

def run_tests(verbose=False):
    """Run all unit tests"""
    # Discover and run all tests
    loader = unittest.TestLoader()
    start_dir = os.path.dirname(os.path.abspath(__file__))
    suite = loader.discover(start_dir, pattern='test_*.py')

    # Run tests with appropriate verbosity
    verbosity = 2 if verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)

    # Return exit code
    return 0 if result.wasSuccessful() else 1

def run_specific_test(test_file):
    """Run a specific test file"""
    loader = unittest.TestLoader()
    suite = loader.discover('.', pattern=test_file)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    # Parse command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] in ['-v', '--verbose']:
            exit_code = run_tests(verbose=True)
        elif sys.argv[1] in ['-h', '--help']:
            print("Usage: python3 run_tests.py [OPTIONS] [TEST_FILE]")
            print("\nOptions:")
            print("  -v, --verbose    Run tests with verbose output")
            print("  -h, --help       Show this help message")
            print("\nTest Files:")
            print("  test_send.py           Run only send.py tests")
            print("  test_receive.py        Run only receive.py tests")
            print("  test_bidirectional.py  Run only bidirectional.py tests")
            print("\nExamples:")
            print("  python3 run_tests.py                    # Run all tests")
            print("  python3 run_tests.py -v                 # Run all tests (verbose)")
            print("  python3 run_tests.py test_send.py       # Run send tests only")
            exit_code = 0
        elif sys.argv[1].startswith('test_'):
            exit_code = run_specific_test(sys.argv[1])
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use --help for usage information")
            exit_code = 1
    else:
        exit_code = run_tests()

    sys.exit(exit_code)

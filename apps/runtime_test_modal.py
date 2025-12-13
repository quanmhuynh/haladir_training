import modal
import subprocess
import tempfile
import os

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "build-essential",
        "gcc",
        "make",
    )
)

app = modal.App("run_check", image=image)

@app.function(
    max_containers=50,
    timeout=120,
)
def check_runtime(c_code: str, runtime_timeout: int = 30) -> bool:
    """
    Runs C code to check if all unit tests (asserts) pass.
    Assumes code is valid and compilable.
    
    Args:
        c_code: The C source code containing unit tests with asserts
        runtime_timeout: Maximum time in seconds for the program to run
        
    Returns:
        True if all tests pass (exit code 0)
        False if any assert triggers or runtime fails
    """
    print(f"\n{'='*80}")
    print(f"CHECK_RUNTIME")
    print(f"{'='*80}")
    print(f"Input code length: {len(c_code) if c_code else 0} chars")
    print(f"Runtime timeout: {runtime_timeout} seconds")
    print(f"\n--- INPUT CODE (first 500 chars) ---")
    if c_code:
        print(c_code[:500])
        if len(c_code) > 500:
            print(f"... (truncated, total length: {len(c_code)} chars)")
    else:
        print("(empty)")
    print(f"--- END INPUT CODE ---\n")
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = os.path.join(temp_dir, "test.c")
            executable_file = os.path.join(temp_dir, "test")
            
            with open(source_file, "w") as f:
                f.write(c_code)
            
            # Compile silently (just to get executable)
            compile_result = subprocess.run(
                ["gcc", source_file, "-o", executable_file, "-lm"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            if compile_result.returncode != 0:
                print(f"Note: Compilation failed, cannot run tests")
                return False
            
            # Run the executable
            print(f"Running executable...")
            
            try:
                run_result = subprocess.run(
                    [executable_file],
                    capture_output=True,
                    text=True,
                    timeout=runtime_timeout,
                )
            except subprocess.TimeoutExpired as e:
                print(f"\n--- RUNTIME TIMEOUT ---")
                print(f"Execution timed out after {runtime_timeout} seconds")
                print(f"--- END RUNTIME TIMEOUT ---\n")
                print(f"✗ Runtime TIMEOUT")
                print(f"\n{'='*80}")
                print(f"FAILED - Runtime timed out")
                print(f"{'='*80}\n")
                return False
            
            print(f"Runtime return code: {run_result.returncode}")
            print(f"\n--- PROGRAM STDOUT ---")
            print(run_result.stdout if run_result.stdout else "(empty)")
            print(f"--- END PROGRAM STDOUT ---")
            if run_result.stderr:
                print(f"\n--- PROGRAM STDERR ---")
                print(run_result.stderr)
                print(f"--- END PROGRAM STDERR ---")
            print()

            if run_result.returncode == 0:
                print(f"✓ All unit tests PASSED")
                print(f"\n{'='*80}")
                print(f"SUCCESS - All tests passed (exit code 0)")
                print(f"{'='*80}\n")
                return True
            else:
                print(f"✗ Unit tests FAILED")
                print(f"Exit code: {run_result.returncode}")
                if run_result.returncode < 0:
                    import signal
                    sig_num = -run_result.returncode
                    sig_name = signal.Signals(sig_num).name if sig_num in signal.Signals._value2member_map_ else f"Signal {sig_num}"
                    print(f"Process terminated by signal: {sig_name}")
                print(f"\n{'='*80}")
                print(f"FAILED - Tests failed or crashed (exit code {run_result.returncode})")
                print(f"{'='*80}\n")
                return False
                
    except Exception as e:
        print(f"\n--- EXCEPTION ---")
        print(f"Runtime check error: {e}")
        print(f"Error type: {type(e).__name__}")
        print(f"--- END EXCEPTION ---\n")
        print(f"\n{'='*80}")
        print(f"FAILED - Exception occurred")
        print(f"{'='*80}\n")
        return False


# Example usage:
# check_runtime = modal.Function.from_name("run_check", "check_runtime")
# 
# c_code = """
# #include <assert.h>
# 
# int add(int a, int b) { return a + b; }
# 
# int main() {
#     assert(add(2, 3) == 5);
#     assert(add(1, 1) == 2);
#     return 0;
# }
# """
# 
# result = check_runtime.remote(c_code)  # Returns True
# print(f"Tests passed: {result}")
